import discord
from discord.ext import commands, tasks
from dotenv import load_dotenv
from supabase import create_client
from datetime import datetime, timezone, date, timedelta
import os
import csv
import io
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

load_dotenv()

url = os.getenv("SUPABASE_URL")
key = os.getenv("SUPABASE_KEY")

supabase = create_client(url, key)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def month_start() -> str:
    """ISO timestamp for the first moment of the current month (UTC)."""
    now = datetime.now(timezone.utc)
    return datetime(now.year, now.month, 1, tzinfo=timezone.utc).isoformat()


def last_month_start() -> str:
    """ISO timestamp for the first moment of last month (UTC)."""
    now = datetime.now(timezone.utc)
    if now.month == 1:
        start = datetime(now.year - 1, 12, 1, tzinfo=timezone.utc)
    else:
        start = datetime(now.year, now.month - 1, 1, tzinfo=timezone.utc)
    return start.isoformat()


def progress_bar(spent: float, limit: float, length: int = 10) -> str:
    ratio = min(spent / limit, 1.0) if limit > 0 else 0
    filled = round(ratio * length)
    return "[" + "█" * filled + "░" * (length - filled) + f"] {ratio * 100:.0f}%"


async def send_budget_alert(interaction: discord.Interaction, user_id: str, category: str):
    """Fire a followup warning if spending is near or over the monthly budget."""
    try:
        budget_resp = (
            supabase.table("budgets")
            .select("monthly_limit")
            .eq("user_id", user_id)
            .eq("category", category)
            .execute()
        )
        if not budget_resp.data:
            return
        limit = float(budget_resp.data[0]["monthly_limit"])
        spent_resp = (
            supabase.table("transactions")
            .select("amount")
            .eq("user_id", user_id)
            .eq("type", "expense")
            .eq("category", category)
            .gte("created_at", month_start())
            .execute()
        )
        spent = sum(float(r["amount"]) for r in spent_resp.data) if spent_resp.data else 0
        if spent >= limit:
            await interaction.followup.send(
                f"⚠️ **Budget Exceeded!** You've spent ₱{spent:.2f} of your ₱{limit:.2f} limit for **{category}** this month.",
                ephemeral=True,
            )
        elif spent >= limit * 0.8:
            await interaction.followup.send(
                f"⚠️ **Budget Warning:** You're at {spent / limit * 100:.0f}% of your ₱{limit:.2f} limit for **{category}** this month.",
                ephemeral=True,
            )
    except Exception:
        pass

# ---------------------------------------------------------------------------
# Modals
# ---------------------------------------------------------------------------

class ExpenseModal(discord.ui.Modal, title="Log an Expense"):
    amount = discord.ui.TextInput(
        label="Amount",
        placeholder="e.g. 25.50",
        required=True,
    )
    category = discord.ui.TextInput(
        label="Category",
        placeholder="e.g. Food, Transport, Entertainment",
        required=True,
    )
    description = discord.ui.TextInput(
        label="Description",
        placeholder="e.g. Lunch at McDonald's",
        required=True,
        style=discord.TextStyle.short,
    )

    async def on_submit(self, interaction: discord.Interaction):
        try:
            amount_val = float(self.amount.value)
        except ValueError:
            await interaction.response.send_message(
                "Invalid amount — please enter a number like `25.50`.", ephemeral=True
            )
            return

        user_id = str(interaction.user.id)
        data = {
            "user_id": user_id,
            "type": "expense",
            "amount": amount_val,
            "category": self.category.value,
            "description": self.description.value,
        }

        try:
            supabase.table("transactions").insert(data).execute()
            embed = discord.Embed(title="Expense Recorded ✅", color=discord.Color.red())
            embed.add_field(name="Amount", value=f"₱{amount_val:.2f}", inline=True)
            embed.add_field(name="Category", value=self.category.value, inline=True)
            embed.add_field(name="Description", value=self.description.value, inline=False)
            await interaction.response.send_message(embed=embed)
            await send_budget_alert(interaction, user_id, self.category.value)
        except Exception as e:
            print(e)
            await interaction.response.send_message("Failed to record expense.", ephemeral=True)


class IncomeModal(discord.ui.Modal, title="Log Income"):
    amount = discord.ui.TextInput(
        label="Amount",
        placeholder="e.g. 500.00",
        required=True,
    )
    category = discord.ui.TextInput(
        label="Category",
        placeholder="e.g. Salary, Freelance, Gift",
        required=True,
    )
    description = discord.ui.TextInput(
        label="Description",
        placeholder="e.g. Monthly salary",
        required=True,
        style=discord.TextStyle.short,
    )

    async def on_submit(self, interaction: discord.Interaction):
        try:
            amount_val = float(self.amount.value)
        except ValueError:
            await interaction.response.send_message(
                "Invalid amount — please enter a number like `500.00`.", ephemeral=True
            )
            return

        user_id = str(interaction.user.id)
        data = {
            "user_id": user_id,
            "type": "income",
            "amount": amount_val,
            "category": self.category.value,
            "description": self.description.value,
        }

        try:
            supabase.table("transactions").insert(data).execute()
            embed = discord.Embed(title="Income Recorded ✅", color=discord.Color.green())
            embed.add_field(name="Amount", value=f"₱{amount_val:.2f}", inline=True)
            embed.add_field(name="Category", value=self.category.value, inline=True)
            embed.add_field(name="Description", value=self.description.value, inline=False)
            await interaction.response.send_message(embed=embed)
        except Exception as e:
            print(e)
            await interaction.response.send_message("Failed to record income.", ephemeral=True)


class SetBudgetModal(discord.ui.Modal, title="Set Monthly Budget"):
    category = discord.ui.TextInput(
        label="Category",
        placeholder="e.g. Food, Transport, Entertainment",
        required=True,
    )
    monthly_limit = discord.ui.TextInput(
        label="Monthly Limit (₱)",
        placeholder="e.g. 3000.00",
        required=True,
    )

    async def on_submit(self, interaction: discord.Interaction):
        try:
            limit_val = float(self.monthly_limit.value)
        except ValueError:
            await interaction.response.send_message(
                "Invalid amount — please enter a number like `3000.00`.", ephemeral=True
            )
            return
        user_id = str(interaction.user.id)
        try:
            existing = (
                supabase.table("budgets")
                .select("id")
                .eq("user_id", user_id)
                .eq("category", self.category.value)
                .execute()
            )
            if existing.data:
                supabase.table("budgets").update({"monthly_limit": limit_val}).eq("id", existing.data[0]["id"]).execute()
            else:
                supabase.table("budgets").insert({
                    "user_id": user_id,
                    "category": self.category.value,
                    "monthly_limit": limit_val,
                }).execute()
            embed = discord.Embed(title="Budget Set ✅", color=discord.Color.gold())
            embed.add_field(name="Category", value=self.category.value, inline=True)
            embed.add_field(name="Monthly Limit", value=f"₱{limit_val:.2f}", inline=True)
            await interaction.response.send_message(embed=embed, ephemeral=True)
        except Exception as e:
            print(e)
            await interaction.response.send_message("Failed to set budget.", ephemeral=True)


class SetGoalModal(discord.ui.Modal, title="Set a Savings Goal"):
    name = discord.ui.TextInput(
        label="Goal Name",
        placeholder="e.g. Emergency Fund, Vacation, Laptop",
        required=True,
    )
    target_amount = discord.ui.TextInput(
        label="Target Amount (₱)",
        placeholder="e.g. 10000.00",
        required=True,
    )
    deadline = discord.ui.TextInput(
        label="Deadline (YYYY-MM-DD, optional)",
        placeholder="e.g. 2026-12-31",
        required=False,
    )

    async def on_submit(self, interaction: discord.Interaction):
        try:
            target_val = float(self.target_amount.value)
        except ValueError:
            await interaction.response.send_message(
                "Invalid amount — please enter a number like `10000.00`.", ephemeral=True
            )
            return
        deadline_val = self.deadline.value.strip() or None
        user_id = str(interaction.user.id)
        try:
            supabase.table("goals").insert({
                "user_id": user_id,
                "name": self.name.value,
                "target_amount": target_val,
                "current_amount": 0,
                "deadline": deadline_val,
            }).execute()
            embed = discord.Embed(title="🎯 Goal Created ✅", color=discord.Color.teal())
            embed.add_field(name="Goal", value=self.name.value, inline=True)
            embed.add_field(name="Target", value=f"₱{target_val:.2f}", inline=True)
            if deadline_val:
                embed.add_field(name="Deadline", value=deadline_val, inline=True)
            await interaction.response.send_message(embed=embed, ephemeral=True)
        except Exception as e:
            print(e)
            await interaction.response.send_message("Failed to create goal.", ephemeral=True)


class ContributeGoalModal(discord.ui.Modal, title="Contribute to a Goal"):
    goal_name = discord.ui.TextInput(
        label="Goal Name",
        placeholder="e.g. Emergency Fund",
        required=True,
    )
    amount = discord.ui.TextInput(
        label="Amount to Contribute (₱)",
        placeholder="e.g. 500.00",
        required=True,
    )

    async def on_submit(self, interaction: discord.Interaction):
        try:
            amount_val = float(self.amount.value)
        except ValueError:
            await interaction.response.send_message(
                "Invalid amount — please enter a number like `500.00`.", ephemeral=True
            )
            return
        user_id = str(interaction.user.id)
        try:
            resp = (
                supabase.table("goals")
                .select("id, current_amount, target_amount")
                .eq("user_id", user_id)
                .ilike("name", self.goal_name.value)
                .limit(1)
                .execute()
            )
            if not resp.data:
                await interaction.response.send_message(
                    f"No goal named **{self.goal_name.value}** found. Check your goals with `!goals`.",
                    ephemeral=True,
                )
                return
            row = resp.data[0]
            new_amount = float(row["current_amount"]) + amount_val
            supabase.table("goals").update({"current_amount": new_amount}).eq("id", row["id"]).execute()
            target = float(row["target_amount"])
            bar = progress_bar(new_amount, target)
            embed = discord.Embed(title="💰 Contribution Added ✅", color=discord.Color.teal())
            embed.add_field(name="Goal", value=self.goal_name.value, inline=True)
            embed.add_field(name="Contributed", value=f"₱{amount_val:.2f}", inline=True)
            embed.add_field(name="Progress", value=f"{bar}  ₱{new_amount:.2f} / ₱{target:.2f}", inline=False)
            if new_amount >= target:
                embed.add_field(name="🎉", value="Goal reached!", inline=False)
            await interaction.response.send_message(embed=embed, ephemeral=True)
        except Exception as e:
            print(e)
            await interaction.response.send_message("Failed to update goal.", ephemeral=True)


class SetRecurringModal(discord.ui.Modal, title="Add Recurring Transaction"):
    type_ = discord.ui.TextInput(
        label="Type (income or expense)",
        placeholder="income / expense",
        required=True,
    )
    amount = discord.ui.TextInput(
        label="Amount (₱)",
        placeholder="e.g. 200.00",
        required=True,
    )
    category = discord.ui.TextInput(
        label="Category",
        placeholder="e.g. Subscriptions, Salary",
        required=True,
    )
    description = discord.ui.TextInput(
        label="Description",
        placeholder="e.g. Netflix subscription",
        required=True,
    )
    frequency = discord.ui.TextInput(
        label="Frequency (weekly or monthly)",
        placeholder="weekly / monthly",
        required=True,
    )

    async def on_submit(self, interaction: discord.Interaction):
        type_val = self.type_.value.strip().lower()
        freq_val = self.frequency.value.strip().lower()
        if type_val not in ("income", "expense"):
            await interaction.response.send_message("Type must be `income` or `expense`.", ephemeral=True)
            return
        if freq_val not in ("weekly", "monthly"):
            await interaction.response.send_message("Frequency must be `weekly` or `monthly`.", ephemeral=True)
            return
        try:
            amount_val = float(self.amount.value)
        except ValueError:
            await interaction.response.send_message("Invalid amount.", ephemeral=True)
            return
        user_id = str(interaction.user.id)
        try:
            supabase.table("recurring").insert({
                "user_id": user_id,
                "type": type_val,
                "amount": amount_val,
                "category": self.category.value,
                "description": self.description.value,
                "frequency": freq_val,
                "last_run": None,
            }).execute()
            embed = discord.Embed(title="🔁 Recurring Transaction Set ✅", color=discord.Color.purple())
            embed.add_field(name="Type", value=type_val.capitalize(), inline=True)
            embed.add_field(name="Amount", value=f"₱{amount_val:.2f}", inline=True)
            embed.add_field(name="Category", value=self.category.value, inline=True)
            embed.add_field(name="Frequency", value=freq_val.capitalize(), inline=True)
            await interaction.response.send_message(embed=embed, ephemeral=True)
        except Exception as e:
            print(e)
            await interaction.response.send_message("Failed to set recurring transaction.", ephemeral=True)


# ---------------------------------------------------------------------------
# Button Views
# ---------------------------------------------------------------------------

class ExpenseView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=60)

    @discord.ui.button(label="Fill in Expense", style=discord.ButtonStyle.red, emoji="💸")
    async def open_expense_modal(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(ExpenseModal())


class IncomeView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=60)

    @discord.ui.button(label="Fill in Income", style=discord.ButtonStyle.green, emoji="💰")
    async def open_income_modal(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(IncomeModal())


class SetBudgetView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=60)

    @discord.ui.button(label="Set Budget", style=discord.ButtonStyle.gray, emoji="🎯")
    async def open_budget_modal(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(SetBudgetModal())


class DeleteSelect(discord.ui.Select):
    def __init__(self, rows):
        self.rows = rows
        options = []
        for row in rows:
            sign = "+" if row["type"] == "income" else "-"
            label = f"{row['created_at'][:10]} {row['category']} {sign}₱{float(row['amount']):.2f}"
            desc = (row["description"] or "")[:50]
            options.append(discord.SelectOption(label=label[:100], value=row["id"], description=desc))
        super().__init__(placeholder="Pick a transaction to delete…", options=options, min_values=1, max_values=1)

    async def callback(self, interaction: discord.Interaction):
        tx_id = self.values[0]
        row = next((r for r in self.rows if r["id"] == tx_id), None)
        try:
            supabase.table("transactions").delete().eq("id", tx_id).execute()
            sign = "+" if row["type"] == "income" else "-"
            embed = discord.Embed(title="🗑️ Transaction Deleted", color=discord.Color.orange())
            embed.add_field(name="Amount", value=f"{sign}₱{float(row['amount']):.2f}", inline=True)
            embed.add_field(name="Category", value=row["category"], inline=True)
            embed.add_field(name="Description", value=row["description"] or "—", inline=False)
            await interaction.response.edit_message(embed=embed, view=None)
        except Exception as e:
            print(e)
            await interaction.response.send_message("Failed to delete transaction.", ephemeral=True)


class DeleteView(discord.ui.View):
    def __init__(self, rows):
        super().__init__(timeout=60)
        self.add_item(DeleteSelect(rows))


class SetGoalView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=60)

    @discord.ui.button(label="Set Goal", style=discord.ButtonStyle.blurple, emoji="🎯")
    async def open_goal_modal(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(SetGoalModal())


class ContributeView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=60)

    @discord.ui.button(label="Contribute", style=discord.ButtonStyle.green, emoji="💰")
    async def open_contribute_modal(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(ContributeGoalModal())


class SetRecurringView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=60)

    @discord.ui.button(label="Add Recurring", style=discord.ButtonStyle.blurple, emoji="🔁")
    async def open_recurring_modal(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(SetRecurringModal())


class MenuView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=120)

    @discord.ui.button(label="Log Expense", style=discord.ButtonStyle.red, emoji="💸")
    async def log_expense(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(ExpenseModal())

    @discord.ui.button(label="Log Income", style=discord.ButtonStyle.green, emoji="💰")
    async def log_income(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(IncomeModal())

    @discord.ui.button(label="This Month", style=discord.ButtonStyle.blurple, emoji="📊")
    async def check_balance(self, interaction: discord.Interaction, button: discord.ui.Button):
        await _send_balance(interaction, ephemeral=True)

    @discord.ui.button(label="History", style=discord.ButtonStyle.gray, emoji="📋")
    async def check_history(self, interaction: discord.Interaction, button: discord.ui.Button):
        await _send_history(interaction, ephemeral=True)

    @discord.ui.button(label="Budgets", style=discord.ButtonStyle.gray, emoji="🎯")
    async def check_budgets(self, interaction: discord.Interaction, button: discord.ui.Button):
        await _send_budgets(interaction, ephemeral=True)

# ---------------------------------------------------------------------------
# Shared logic (commands + buttons both call these)
# ---------------------------------------------------------------------------

async def _send_balance(ctx_or_interaction, ephemeral: bool = False):
    """Monthly balance summary. Works for ctx (commands) and Interaction (buttons)."""
    is_ix = isinstance(ctx_or_interaction, discord.Interaction)
    user_id = str(ctx_or_interaction.user.id if is_ix else ctx_or_interaction.author.id)
    ms = month_start()
    try:
        income_resp = (
            supabase.table("transactions")
            .select("amount")
            .eq("user_id", user_id)
            .eq("type", "income")
            .gte("created_at", ms)
            .execute()
        )
        expense_resp = (
            supabase.table("transactions")
            .select("amount")
            .eq("user_id", user_id)
            .eq("type", "expense")
            .gte("created_at", ms)
            .execute()
        )
    except Exception as e:
        print(e)
        msg = "Failed to fetch financial data."
        if is_ix:
            await ctx_or_interaction.response.send_message(msg, ephemeral=True)
        else:
            await ctx_or_interaction.send(msg)
        return

    total_income = sum(float(r["amount"]) for r in (income_resp.data or []))
    total_expense = sum(float(r["amount"]) for r in (expense_resp.data or []))
    balance_val = total_income - total_expense
    now = datetime.now(timezone.utc)
    color = discord.Color.green() if balance_val >= 0 else discord.Color.red()
    embed = discord.Embed(title=f"📊 {now.strftime('%B %Y')} Summary", color=color)
    embed.add_field(name="Income", value=f"₱{total_income:.2f}", inline=True)
    embed.add_field(name="Expenses", value=f"₱{total_expense:.2f}", inline=True)
    embed.add_field(name="Balance", value=f"₱{balance_val:.2f}", inline=True)
    if is_ix:
        await ctx_or_interaction.response.send_message(embed=embed, ephemeral=ephemeral)
    else:
        await ctx_or_interaction.send(embed=embed)


async def _send_history(ctx_or_interaction, ephemeral: bool = False):
    """Last 10 transactions."""
    is_ix = isinstance(ctx_or_interaction, discord.Interaction)
    user_id = str(ctx_or_interaction.user.id if is_ix else ctx_or_interaction.author.id)
    try:
        resp = (
            supabase.table("transactions")
            .select("type, amount, category, description, created_at")
            .eq("user_id", user_id)
            .order("created_at", desc=True)
            .limit(10)
            .execute()
        )
    except Exception as e:
        print(e)
        msg = "Failed to fetch transaction history."
        if is_ix:
            await ctx_or_interaction.response.send_message(msg, ephemeral=True)
        else:
            await ctx_or_interaction.send(msg)
        return

    rows = resp.data or []
    if not rows:
        msg = "No transactions found."
        if is_ix:
            await ctx_or_interaction.response.send_message(msg, ephemeral=ephemeral)
        else:
            await ctx_or_interaction.send(msg)
        return

    embed = discord.Embed(title="📋 Last 10 Transactions", color=discord.Color.blurple())
    for row in rows:
        sign = "+" if row["type"] == "income" else "-"
        icon = "🟢" if row["type"] == "income" else "🔴"
        date_str = row["created_at"][:10]
        embed.add_field(
            name=f"{icon} {date_str} — {row['category']}",
            value=f"{sign}₱{float(row['amount']):.2f} · {row['description']}",
            inline=False,
        )
    if is_ix:
        await ctx_or_interaction.response.send_message(embed=embed, ephemeral=ephemeral)
    else:
        await ctx_or_interaction.send(embed=embed)


async def _send_budgets(ctx_or_interaction, ephemeral: bool = False):
    """Budget progress bars for the current month."""
    is_ix = isinstance(ctx_or_interaction, discord.Interaction)
    user_id = str(ctx_or_interaction.user.id if is_ix else ctx_or_interaction.author.id)
    ms = month_start()
    try:
        budget_resp = (
            supabase.table("budgets")
            .select("category, monthly_limit")
            .eq("user_id", user_id)
            .execute()
        )
    except Exception as e:
        print(e)
        msg = "Failed to fetch budgets."
        if is_ix:
            await ctx_or_interaction.response.send_message(msg, ephemeral=True)
        else:
            await ctx_or_interaction.send(msg)
        return

    budgets = budget_resp.data or []
    if not budgets:
        msg = "No budgets set. Use `!setbudget` to create one."
        if is_ix:
            await ctx_or_interaction.response.send_message(msg, ephemeral=ephemeral)
        else:
            await ctx_or_interaction.send(msg)
        return

    now = datetime.now(timezone.utc)
    embed = discord.Embed(title=f"🎯 Budgets — {now.strftime('%B %Y')}", color=discord.Color.gold())
    for b in budgets:
        cat = b["category"]
        limit = float(b["monthly_limit"])
        try:
            spent_resp = (
                supabase.table("transactions")
                .select("amount")
                .eq("user_id", user_id)
                .eq("type", "expense")
                .eq("category", cat)
                .gte("created_at", ms)
                .execute()
            )
            spent = sum(float(r["amount"]) for r in spent_resp.data) if spent_resp.data else 0
        except Exception:
            spent = 0
        bar = progress_bar(spent, limit)
        if spent > limit:
            status = "🔴 Over budget!"
        elif spent >= limit * 0.8:
            status = "🟡 Getting close"
        else:
            status = "🟢 On track"
        embed.add_field(
            name=f"{cat} — ₱{spent:.2f} / ₱{limit:.2f}",
            value=f"{bar}  {status}",
            inline=False,
        )
    if is_ix:
        await ctx_or_interaction.response.send_message(embed=embed, ephemeral=ephemeral)
    else:
        await ctx_or_interaction.send(embed=embed)


async def _send_breakdown(ctx_or_interaction, ephemeral: bool = False):
    """Category % breakdown of expenses this month."""
    is_ix = isinstance(ctx_or_interaction, discord.Interaction)
    user_id = str(ctx_or_interaction.user.id if is_ix else ctx_or_interaction.author.id)
    ms = month_start()
    try:
        resp = (
            supabase.table("transactions")
            .select("category, amount")
            .eq("user_id", user_id)
            .eq("type", "expense")
            .gte("created_at", ms)
            .execute()
        )
    except Exception as e:
        print(e)
        msg = "Failed to fetch expense data."
        if is_ix:
            await ctx_or_interaction.response.send_message(msg, ephemeral=True)
        else:
            await ctx_or_interaction.send(msg)
        return
    rows = resp.data or []
    if not rows:
        msg = "No expenses this month yet."
        if is_ix:
            await ctx_or_interaction.response.send_message(msg, ephemeral=ephemeral)
        else:
            await ctx_or_interaction.send(msg)
        return
    totals: dict = {}
    for row in rows:
        cat = row["category"]
        totals[cat] = totals.get(cat, 0) + float(row["amount"])
    grand_total = sum(totals.values())
    now = datetime.now(timezone.utc)
    embed = discord.Embed(title=f"🍩 Spending Breakdown — {now.strftime('%B %Y')}", color=discord.Color.orange())
    for cat, amt in sorted(totals.items(), key=lambda x: x[1], reverse=True):
        pct = amt / grand_total * 100
        bar = progress_bar(amt, grand_total)
        embed.add_field(name=f"{cat}  ₱{amt:.2f} ({pct:.0f}%)", value=bar, inline=False)
    embed.set_footer(text=f"Total: ₱{grand_total:.2f}")
    if is_ix:
        await ctx_or_interaction.response.send_message(embed=embed, ephemeral=ephemeral)
    else:
        await ctx_or_interaction.send(embed=embed)


async def _send_insights(ctx_or_interaction, ephemeral: bool = False):
    """Compare this month vs last month spending by category."""
    is_ix = isinstance(ctx_or_interaction, discord.Interaction)
    user_id = str(ctx_or_interaction.user.id if is_ix else ctx_or_interaction.author.id)
    ms = month_start()
    lms = last_month_start()
    try:
        this_resp = (
            supabase.table("transactions")
            .select("category, amount")
            .eq("user_id", user_id)
            .eq("type", "expense")
            .gte("created_at", ms)
            .execute()
        )
        last_resp = (
            supabase.table("transactions")
            .select("category, amount")
            .eq("user_id", user_id)
            .eq("type", "expense")
            .gte("created_at", lms)
            .lt("created_at", ms)
            .execute()
        )
    except Exception as e:
        print(e)
        msg = "Failed to fetch insight data."
        if is_ix:
            await ctx_or_interaction.response.send_message(msg, ephemeral=True)
        else:
            await ctx_or_interaction.send(msg)
        return

    def tally(rows):
        t = {}
        for r in rows:
            t[r["category"]] = t.get(r["category"], 0) + float(r["amount"])
        return t

    this_month = tally(this_resp.data or [])
    last_month = tally(last_resp.data or [])
    all_cats = sorted(set(this_month) | set(last_month))
    if not all_cats:
        msg = "Not enough data to generate insights yet."
        if is_ix:
            await ctx_or_interaction.response.send_message(msg, ephemeral=ephemeral)
        else:
            await ctx_or_interaction.send(msg)
        return
    now = datetime.now(timezone.utc)
    embed = discord.Embed(
        title=f"📈 Spending Insights — {now.strftime('%B %Y')} vs Last Month",
        color=discord.Color.blurple(),
    )
    for cat in all_cats:
        this = this_month.get(cat, 0)
        last = last_month.get(cat, 0)
        if last == 0:
            diff_str = f"₱{this:.2f} (new this month)"
        else:
            diff = this - last
            pct = diff / last * 100
            arrow = "🔺" if diff > 0 else ("🔻" if diff < 0 else "➡️")
            diff_str = f"₱{this:.2f} vs ₱{last:.2f}  {arrow} {pct:+.0f}%"
        embed.add_field(name=cat, value=diff_str, inline=False)
    if is_ix:
        await ctx_or_interaction.response.send_message(embed=embed, ephemeral=ephemeral)
    else:
        await ctx_or_interaction.send(embed=embed)


async def _send_goals(ctx_or_interaction, ephemeral: bool = False):
    """Show all savings goals with progress bars."""
    is_ix = isinstance(ctx_or_interaction, discord.Interaction)
    user_id = str(ctx_or_interaction.user.id if is_ix else ctx_or_interaction.author.id)
    try:
        resp = (
            supabase.table("goals")
            .select("name, target_amount, current_amount, deadline")
            .eq("user_id", user_id)
            .execute()
        )
    except Exception as e:
        print(e)
        msg = "Failed to fetch goals."
        if is_ix:
            await ctx_or_interaction.response.send_message(msg, ephemeral=True)
        else:
            await ctx_or_interaction.send(msg)
        return
    goals = resp.data or []
    if not goals:
        msg = "No goals set. Use `!setgoal` to create one."
        if is_ix:
            await ctx_or_interaction.response.send_message(msg, ephemeral=ephemeral)
        else:
            await ctx_or_interaction.send(msg)
        return
    embed = discord.Embed(title="🏆 Savings Goals", color=discord.Color.teal())
    for g in goals:
        current = float(g["current_amount"])
        target = float(g["target_amount"])
        bar = progress_bar(current, target)
        deadline_str = f" · Due {g['deadline']}" if g.get("deadline") else ""
        status = "✅ Complete!" if current >= target else f"₱{current:.2f} / ₱{target:.2f}{deadline_str}"
        embed.add_field(name=g["name"], value=f"{bar}  {status}", inline=False)
    if is_ix:
        await ctx_or_interaction.response.send_message(embed=embed, ephemeral=ephemeral)
    else:
        await ctx_or_interaction.send(embed=embed)


# ---------------------------------------------------------------------------
# Bot setup
# ---------------------------------------------------------------------------

intents = discord.Intents.default()
intents.message_content = True

client = commands.Bot(command_prefix='!', intents=intents, help_command=None)

# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------

@client.event
async def on_ready():
    print('FinTrack is ready to use!')
    print('------------------------------')
    if not process_recurring.is_running():
        process_recurring.start()


@tasks.loop(hours=24)
async def process_recurring():
    """Auto-log recurring transactions that are due."""
    today = date.today()
    try:
        resp = supabase.table("recurring").select("*").execute()
        rows = resp.data or []
    except Exception as e:
        print(f"Recurring task fetch error: {e}")
        return
    for row in rows:
        last = date.fromisoformat(row["last_run"]) if row.get("last_run") else None
        due = False
        if row["frequency"] == "weekly":
            due = last is None or (today - last).days >= 7
        elif row["frequency"] == "monthly":
            due = last is None or (last.year, last.month) < (today.year, today.month)
        if due:
            try:
                supabase.table("transactions").insert({
                    "user_id": row["user_id"],
                    "type": row["type"],
                    "amount": row["amount"],
                    "category": row["category"],
                    "description": row["description"],
                }).execute()
                supabase.table("recurring").update({"last_run": today.isoformat()}).eq("id", row["id"]).execute()
                print(f"Auto-logged recurring '{row['description']}' for user {row['user_id']}")
            except Exception as e:
                print(f"Failed to log recurring {row['id']}: {e}")

# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

@client.command()
async def hello(ctx):
    embed = discord.Embed(
        title="Welcome to FinTrack! 👋",
        description=(
            "I'm your personal finance assistant.\n\n"
            "Use `!menu` to open an interactive dashboard,\n"
            "or type `!help` to see all available commands."
        ),
        color=discord.Color.blue()
    )
    await ctx.send(embed=embed)


@client.command(name='help')
async def help_command(ctx):
    embed = discord.Embed(
        title='FinTrack — Command Guide',
        description='Use `!menu` for a fully interactive dashboard with pop-up forms.',
        color=discord.Color.blue()
    )
    embed.add_field(name='!menu', value='Open the interactive dashboard.', inline=False)
    embed.add_field(name='!expense', value='Log an expense via pop-up form.', inline=False)
    embed.add_field(name='!income', value='Log income via pop-up form.', inline=False)
    embed.add_field(name='!balance', value="Show this month's income, expenses, and balance.", inline=False)
    embed.add_field(name='!history', value='Show your last 10 transactions.', inline=False)
    embed.add_field(name='!breakdown', value="Category % breakdown of this month's expenses.", inline=False)
    embed.add_field(name='!insights', value='Compare this month vs last month by category.', inline=False)
    embed.add_field(name='!setbudget', value='Set a monthly spending limit for a category.', inline=False)
    embed.add_field(name='!budgets', value='View all budget limits with progress bars.', inline=False)
    embed.add_field(name='!setgoal', value='Create a savings goal with a target and deadline.', inline=False)
    embed.add_field(name='!goals', value='View all savings goals and progress.', inline=False)
    embed.add_field(name='!contribute', value='Add money toward a savings goal.', inline=False)
    embed.add_field(name='!setrecurring', value='Add a recurring weekly/monthly transaction.', inline=False)
    embed.add_field(name='!delete', value='Delete a specific transaction via dropdown.', inline=False)
    embed.add_field(name='!export', value='Export all transactions as a CSV to your DMs.', inline=False)
    embed.add_field(name='!undo', value='Delete your most recent transaction.', inline=False)
    embed.add_field(name='!hello', value='Greet the bot.', inline=False)
    embed.add_field(name='!help', value='Show this help message.', inline=False)
    await ctx.send(embed=embed)


@client.command()
async def menu(ctx):
    embed = discord.Embed(
        title="FinTrack Dashboard",
        description="Choose an action below:",
        color=discord.Color.blurple()
    )
    await ctx.send(embed=embed, view=MenuView())


@client.command()
async def expense(ctx):
    embed = discord.Embed(
        description="Click the button below to open the expense form.",
        color=discord.Color.red()
    )
    await ctx.send(embed=embed, view=ExpenseView())


@client.command()
async def income(ctx):
    embed = discord.Embed(
        description="Click the button below to open the income form.",
        color=discord.Color.green()
    )
    await ctx.send(embed=embed, view=IncomeView())


@client.command()
async def balance(ctx):
    await _send_balance(ctx)


@client.command()
async def history(ctx):
    await _send_history(ctx)


@client.command()
async def setbudget(ctx):
    embed = discord.Embed(
        description="Click the button below to set a monthly budget for a category.",
        color=discord.Color.gold()
    )
    await ctx.send(embed=embed, view=SetBudgetView())


@client.command()
async def budgets(ctx):
    await _send_budgets(ctx)


@client.command()
async def breakdown(ctx):
    await _send_breakdown(ctx)


@client.command()
async def insights(ctx):
    await _send_insights(ctx)


@client.command(name="delete")
async def delete_transaction(ctx):
    user_id = str(ctx.author.id)
    try:
        resp = (
            supabase.table("transactions")
            .select("id, type, amount, category, description, created_at")
            .eq("user_id", user_id)
            .order("created_at", desc=True)
            .limit(5)
            .execute()
        )
    except Exception as e:
        print(e)
        await ctx.send("Failed to fetch your transactions.")
        return
    rows = resp.data or []
    if not rows:
        await ctx.send("You have no transactions to delete.")
        return
    embed = discord.Embed(
        title="🗑️ Delete a Transaction",
        description="Select a transaction from the dropdown below:",
        color=discord.Color.orange(),
    )
    await ctx.send(embed=embed, view=DeleteView(rows))


@client.command(name="export")
async def export_transactions(ctx):
    user_id = str(ctx.author.id)
    try:
        resp = (
            supabase.table("transactions")
            .select("type, amount, category, description, created_at")
            .eq("user_id", user_id)
            .order("created_at", desc=True)
            .execute()
        )
    except Exception as e:
        print(e)
        await ctx.send("Failed to fetch your transactions.")
        return
    rows = resp.data or []
    if not rows:
        await ctx.send("No transactions to export.")
        return
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=["date", "type", "amount", "category", "description"])
    writer.writeheader()
    for row in rows:
        writer.writerow({
            "date": row["created_at"][:10],
            "type": row["type"],
            "amount": row["amount"],
            "category": row["category"],
            "description": row["description"] or "",
        })
    output.seek(0)
    file = discord.File(fp=io.BytesIO(output.getvalue().encode()), filename="transactions.csv")
    try:
        await ctx.author.send("📎 Here's your transaction export:", file=file)
        await ctx.send("✅ Sent your export to your DMs!")
    except discord.Forbidden:
        await ctx.send("❌ I couldn't DM you. Please enable DMs from server members.")


@client.command()
async def setgoal(ctx):
    embed = discord.Embed(
        description="Click the button below to create a savings goal.",
        color=discord.Color.teal(),
    )
    await ctx.send(embed=embed, view=SetGoalView())


@client.command()
async def goals(ctx):
    await _send_goals(ctx)


@client.command()
async def contribute(ctx):
    embed = discord.Embed(
        description="Click the button below to contribute to a savings goal.",
        color=discord.Color.teal(),
    )
    await ctx.send(embed=embed, view=ContributeView())


@client.command()
async def setrecurring(ctx):
    embed = discord.Embed(
        description="Click the button below to add a recurring transaction.",
        color=discord.Color.purple(),
    )
    await ctx.send(embed=embed, view=SetRecurringView())


@client.command()
async def undo(ctx):
    user_id = str(ctx.author.id)
    try:
        resp = (
            supabase.table("transactions")
            .select("id, type, amount, category, description")
            .eq("user_id", user_id)
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
    except Exception as e:
        print(e)
        await ctx.send("Failed to fetch your last transaction.")
        return

    if not resp.data:
        await ctx.send("You have no transactions to undo.")
        return

    row = resp.data[0]
    try:
        supabase.table("transactions").delete().eq("id", row["id"]).execute()
        sign = "+" if row["type"] == "income" else "-"
        embed = discord.Embed(title="↩️ Transaction Deleted", color=discord.Color.orange())
        embed.add_field(name="Type", value=row["type"].capitalize(), inline=True)
        embed.add_field(name="Amount", value=f"{sign}₱{float(row['amount']):.2f}", inline=True)
        embed.add_field(name="Category", value=row["category"], inline=True)
        embed.add_field(name="Description", value=row["description"], inline=False)
        await ctx.send(embed=embed)
    except Exception as e:
        print(e)
        await ctx.send("Failed to delete the transaction.")


# Minimal HTTP server so Render's free Web Service tier keeps the bot alive
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")
    def log_message(self, format, *args):
        pass  # suppress access logs

port = int(os.getenv("PORT", 8080))
server = HTTPServer(("0.0.0.0", port), HealthHandler)
threading.Thread(target=server.serve_forever, daemon=True).start()

client.run(os.getenv('BOT_TOKEN'))