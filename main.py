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

        await interaction.response.defer()
        user_id = str(interaction.user.id)
        data = {
            "user_id": user_id,
            "type": "expense",
            "amount": amount_val,
            "category": self.category.value,
            "description": self.description.value,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

        try:
            supabase.table("transactions").insert(data).execute()
            embed = discord.Embed(title="Expense Recorded ✅", color=discord.Color.red())
            embed.add_field(name="Amount", value=f"₱{amount_val:.2f}", inline=True)
            embed.add_field(name="Category", value=self.category.value, inline=True)
            embed.add_field(name="Description", value=self.description.value, inline=False)
            await interaction.followup.send(embed=embed)
            await send_budget_alert(interaction, user_id, self.category.value)
        except Exception as e:
            print(e)
            await interaction.followup.send("Failed to record expense.", ephemeral=True)


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

        await interaction.response.defer()
        user_id = str(interaction.user.id)
        data = {
            "user_id": user_id,
            "type": "income",
            "amount": amount_val,
            "category": self.category.value,
            "description": self.description.value,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

        try:
            supabase.table("transactions").insert(data).execute()
            embed = discord.Embed(title="Income Recorded ✅", color=discord.Color.green())
            embed.add_field(name="Amount", value=f"₱{amount_val:.2f}", inline=True)
            embed.add_field(name="Category", value=self.category.value, inline=True)
            embed.add_field(name="Description", value=self.description.value, inline=False)
            await interaction.followup.send(embed=embed)
        except Exception as e:
            print(e)
            await interaction.followup.send("Failed to record income.", ephemeral=True)


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
        await interaction.response.defer(ephemeral=True)
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
            await interaction.followup.send(embed=embed, ephemeral=True)
        except Exception as e:
            print(e)
            await interaction.followup.send("Failed to set budget.", ephemeral=True)


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
        await interaction.response.defer(ephemeral=True)
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
            await interaction.followup.send(embed=embed, ephemeral=True)
        except Exception as e:
            print(e)
            await interaction.followup.send("Failed to create goal.", ephemeral=True)


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
        await interaction.response.defer(ephemeral=True)
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
                await interaction.followup.send(
                    f"No goal named **{self.goal_name.value}** found. Check your goals with `/goals`.",
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
            await interaction.followup.send(embed=embed, ephemeral=True)
        except Exception as e:
            print(e)
            await interaction.followup.send("Failed to update goal.", ephemeral=True)


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
        await interaction.response.defer(ephemeral=True)
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
            await interaction.followup.send(embed=embed, ephemeral=True)
        except Exception as e:
            print(e)
            await interaction.followup.send("Failed to set recurring transaction.", ephemeral=True)


# ---------------------------------------------------------------------------
# Button Views
# ---------------------------------------------------------------------------

class DeleteSelect(discord.ui.Select):
    def __init__(self, rows):
        self.rows = rows
        options = []
        for row in rows:
            sign = "+" if row["type"] == "income" else "-"
            date_prefix = row["created_at"][:10] if row["created_at"] else "Unknown"
            label = f"{date_prefix} {row['category']} {sign}₱{float(row['amount']):.2f}"
            desc = (row["description"] or "")[:50]
            options.append(discord.SelectOption(label=label[:100], value=row["id"], description=desc))
        super().__init__(placeholder="Pick a transaction to delete…", options=options, min_values=1, max_values=1)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        tx_id = self.values[0]
        row = next((r for r in self.rows if r["id"] == tx_id), None)
        try:
            supabase.table("transactions").delete().eq("id", tx_id).execute()
            sign = "+" if row["type"] == "income" else "-"
            embed = discord.Embed(title="🗑️ Transaction Deleted", color=discord.Color.orange())
            embed.add_field(name="Amount", value=f"{sign}₱{float(row['amount']):.2f}", inline=True)
            embed.add_field(name="Category", value=row["category"], inline=True)
            embed.add_field(name="Description", value=row["description"] or "—", inline=False)
            await interaction.edit_original_response(embed=embed, view=None)
        except Exception as e:
            print(e)
            await interaction.followup.send("Failed to delete transaction.", ephemeral=True)


class DeleteView(discord.ui.View):
    def __init__(self, rows):
        super().__init__(timeout=60)
        self.add_item(DeleteSelect(rows))


# ---------------------------------------------------------------------------
# Budget delete
# ---------------------------------------------------------------------------

class BudgetDeleteSelect(discord.ui.Select):
    def __init__(self, rows):
        self.rows = rows
        options = [
            discord.SelectOption(
                label=f"{r['category']} — ₱{float(r['monthly_limit']):.2f}/mo",
                value=r["id"],
            )
            for r in rows
        ]
        super().__init__(placeholder="Pick a budget to delete…", options=options, min_values=1, max_values=1)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        row = next(r for r in self.rows if r["id"] == self.values[0])
        try:
            supabase.table("budgets").delete().eq("id", row["id"]).execute()
            embed = discord.Embed(title="🗑️ Budget Deleted", color=discord.Color.orange())
            embed.add_field(name="Category", value=row["category"], inline=True)
            embed.add_field(name="Was", value=f"₱{float(row['monthly_limit']):.2f}/mo", inline=True)
            await interaction.edit_original_response(embed=embed, view=None)
        except Exception as e:
            print(e)
            await interaction.followup.send("Failed to delete budget.", ephemeral=True)


class BudgetDeleteView(discord.ui.View):
    def __init__(self, rows):
        super().__init__(timeout=60)
        self.add_item(BudgetDeleteSelect(rows))


# ---------------------------------------------------------------------------
# Goal delete / edit
# ---------------------------------------------------------------------------

class GoalDeleteSelect(discord.ui.Select):
    def __init__(self, rows):
        self.rows = rows
        options = [
            discord.SelectOption(
                label=f"{r['name']} — ₱{float(r['current_amount']):.2f} / ₱{float(r['target_amount']):.2f}",
                value=r["id"],
            )
            for r in rows
        ]
        super().__init__(placeholder="Pick a goal to delete…", options=options, min_values=1, max_values=1)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        row = next(r for r in self.rows if r["id"] == self.values[0])
        try:
            supabase.table("goals").delete().eq("id", row["id"]).execute()
            embed = discord.Embed(title="🗑️ Goal Deleted", color=discord.Color.orange())
            embed.add_field(name="Goal", value=row["name"], inline=True)
            embed.add_field(name="Target Was", value=f"₱{float(row['target_amount']):.2f}", inline=True)
            await interaction.edit_original_response(embed=embed, view=None)
        except Exception as e:
            print(e)
            await interaction.followup.send("Failed to delete goal.", ephemeral=True)


class GoalDeleteView(discord.ui.View):
    def __init__(self, rows):
        super().__init__(timeout=60)
        self.add_item(GoalDeleteSelect(rows))


class GoalEditSelect(discord.ui.Select):
    def __init__(self, rows):
        self.rows = rows
        options = [
            discord.SelectOption(
                label=f"{r['name']} — ₱{float(r['current_amount']):.2f} / ₱{float(r['target_amount']):.2f}",
                value=r["id"],
            )
            for r in rows
        ]
        super().__init__(placeholder="Pick a goal to edit…", options=options, min_values=1, max_values=1)

    async def callback(self, interaction: discord.Interaction):
        row = next(r for r in self.rows if r["id"] == self.values[0])
        await interaction.response.send_modal(GoalEditModal(row))


class GoalEditView(discord.ui.View):
    def __init__(self, rows):
        super().__init__(timeout=60)
        self.add_item(GoalEditSelect(rows))


class GoalEditModal(discord.ui.Modal, title="Edit Savings Goal"):
    def __init__(self, row: dict):
        super().__init__()
        self.row_id = row["id"]
        self.name_input = discord.ui.TextInput(
            label="Goal Name",
            default=row["name"],
            required=True,
        )
        self.target_input = discord.ui.TextInput(
            label="Target Amount (₱)",
            default=str(row["target_amount"]),
            required=True,
        )
        self.current_input = discord.ui.TextInput(
            label="Current Saved Amount (₱)",
            default=str(row["current_amount"]),
            required=True,
        )
        self.deadline_input = discord.ui.TextInput(
            label="Deadline (YYYY-MM-DD, leave blank to clear)",
            default=row.get("deadline") or "",
            required=False,
        )
        self.add_item(self.name_input)
        self.add_item(self.target_input)
        self.add_item(self.current_input)
        self.add_item(self.deadline_input)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            target_val = float(self.target_input.value)
            current_val = float(self.current_input.value)
        except ValueError:
            await interaction.response.send_message("Invalid amount — enter numbers like `5000.00`.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        deadline_val = self.deadline_input.value.strip() or None
        try:
            supabase.table("goals").update({
                "name": self.name_input.value,
                "target_amount": target_val,
                "current_amount": current_val,
                "deadline": deadline_val,
            }).eq("id", self.row_id).execute()
            bar = progress_bar(current_val, target_val)
            embed = discord.Embed(title="✏️ Goal Updated ✅", color=discord.Color.teal())
            embed.add_field(name="Goal", value=self.name_input.value, inline=True)
            embed.add_field(name="Target", value=f"₱{target_val:.2f}", inline=True)
            embed.add_field(name="Progress", value=f"{bar}  ₱{current_val:.2f} / ₱{target_val:.2f}", inline=False)
            if deadline_val:
                embed.add_field(name="Deadline", value=deadline_val, inline=True)
            await interaction.followup.send(embed=embed, ephemeral=True)
        except Exception as e:
            print(e)
            await interaction.followup.send("Failed to update goal.", ephemeral=True)


# ---------------------------------------------------------------------------
# Recurring delete / edit
# ---------------------------------------------------------------------------

class RecurringDeleteSelect(discord.ui.Select):
    def __init__(self, rows):
        self.rows = rows
        options = [
            discord.SelectOption(
                label=f"{r['type'].capitalize()} · {r['category']} · ₱{float(r['amount']):.2f} ({r['frequency']})"[:100],
                description=(r["description"] or "")[:50],
                value=r["id"],
            )
            for r in rows
        ]
        super().__init__(placeholder="Pick a recurring entry to delete…", options=options, min_values=1, max_values=1)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        row = next(r for r in self.rows if r["id"] == self.values[0])
        try:
            supabase.table("recurring").delete().eq("id", row["id"]).execute()
            embed = discord.Embed(title="🗑️ Recurring Entry Deleted", color=discord.Color.orange())
            embed.add_field(name="Type", value=row["type"].capitalize(), inline=True)
            embed.add_field(name="Amount", value=f"₱{float(row['amount']):.2f}", inline=True)
            embed.add_field(name="Category", value=row["category"], inline=True)
            embed.add_field(name="Frequency", value=row["frequency"].capitalize(), inline=True)
            await interaction.edit_original_response(embed=embed, view=None)
        except Exception as e:
            print(e)
            await interaction.followup.send("Failed to delete recurring entry.", ephemeral=True)


class RecurringDeleteView(discord.ui.View):
    def __init__(self, rows):
        super().__init__(timeout=60)
        self.add_item(RecurringDeleteSelect(rows))


class RecurringEditSelect(discord.ui.Select):
    def __init__(self, rows):
        self.rows = rows
        options = [
            discord.SelectOption(
                label=f"{r['type'].capitalize()} · {r['category']} · ₱{float(r['amount']):.2f} ({r['frequency']})"[:100],
                description=(r["description"] or "")[:50],
                value=r["id"],
            )
            for r in rows
        ]
        super().__init__(placeholder="Pick a recurring entry to edit…", options=options, min_values=1, max_values=1)

    async def callback(self, interaction: discord.Interaction):
        row = next(r for r in self.rows if r["id"] == self.values[0])
        await interaction.response.send_modal(RecurringEditModal(row))


class RecurringEditView(discord.ui.View):
    def __init__(self, rows):
        super().__init__(timeout=60)
        self.add_item(RecurringEditSelect(rows))


class RecurringEditModal(discord.ui.Modal, title="Edit Recurring Transaction"):
    def __init__(self, row: dict):
        super().__init__()
        self.row_id = row["id"]
        self.amount_input = discord.ui.TextInput(
            label="Amount (₱)",
            default=str(row["amount"]),
            required=True,
        )
        self.category_input = discord.ui.TextInput(
            label="Category",
            default=row["category"],
            required=True,
        )
        self.description_input = discord.ui.TextInput(
            label="Description",
            default=row["description"] or "",
            required=True,
        )
        self.frequency_input = discord.ui.TextInput(
            label="Frequency (weekly / monthly)",
            default=row["frequency"],
            required=True,
        )
        self.add_item(self.amount_input)
        self.add_item(self.category_input)
        self.add_item(self.description_input)
        self.add_item(self.frequency_input)

    async def on_submit(self, interaction: discord.Interaction):
        freq_val = self.frequency_input.value.strip().lower()
        if freq_val not in ("weekly", "monthly"):
            await interaction.response.send_message("Frequency must be `weekly` or `monthly`.", ephemeral=True)
            return
        try:
            amount_val = float(self.amount_input.value)
        except ValueError:
            await interaction.response.send_message("Invalid amount — enter a number like `200.00`.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        try:
            supabase.table("recurring").update({
                "amount": amount_val,
                "category": self.category_input.value,
                "description": self.description_input.value,
                "frequency": freq_val,
            }).eq("id", self.row_id).execute()
            embed = discord.Embed(title="✏️ Recurring Entry Updated ✅", color=discord.Color.purple())
            embed.add_field(name="Amount", value=f"₱{amount_val:.2f}", inline=True)
            embed.add_field(name="Category", value=self.category_input.value, inline=True)
            embed.add_field(name="Frequency", value=freq_val.capitalize(), inline=True)
            embed.add_field(name="Description", value=self.description_input.value, inline=False)
            await interaction.followup.send(embed=embed, ephemeral=True)
        except Exception as e:
            print(e)
            await interaction.followup.send("Failed to update recurring entry.", ephemeral=True)


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
# Shared logic (slash commands + menu buttons both call these)
# ---------------------------------------------------------------------------

async def _send_balance(interaction: discord.Interaction, ephemeral: bool = False):
    """Monthly balance summary."""
    await interaction.response.defer(ephemeral=ephemeral)
    user_id = str(interaction.user.id)
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
        await interaction.followup.send("Failed to fetch financial data.", ephemeral=True)
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
    await interaction.followup.send(embed=embed, ephemeral=ephemeral)


async def _send_history(interaction: discord.Interaction, ephemeral: bool = False):
    """Last 10 transactions."""
    await interaction.response.defer(ephemeral=ephemeral)
    user_id = str(interaction.user.id)
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
        await interaction.followup.send("Failed to fetch transaction history.", ephemeral=True)
        return

    rows = resp.data or []
    if not rows:
        await interaction.followup.send("No transactions found.", ephemeral=ephemeral)
        return

    embed = discord.Embed(title="📋 Last 10 Transactions", color=discord.Color.blurple())
    for row in rows:
        sign = "+" if row["type"] == "income" else "-"
        icon = "🟢" if row["type"] == "income" else "🔴"
        date_str = row["created_at"][:10] if row["created_at"] else "Unknown"
        embed.add_field(
            name=f"{icon} {date_str} — {row['category']}",
            value=f"{sign}₱{float(row['amount']):.2f} · {row['description']}",
            inline=False,
        )
    await interaction.followup.send(embed=embed, ephemeral=ephemeral)


async def _send_budgets(interaction: discord.Interaction, ephemeral: bool = False):
    """Budget progress bars for the current month."""
    await interaction.response.defer(ephemeral=ephemeral)
    user_id = str(interaction.user.id)
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
        await interaction.followup.send("Failed to fetch budgets.", ephemeral=True)
        return

    budgets = budget_resp.data or []
    if not budgets:
        await interaction.followup.send("No budgets set. Use `/setbudget` to create one.", ephemeral=ephemeral)
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
    await interaction.followup.send(embed=embed, ephemeral=ephemeral)


async def _send_breakdown(interaction: discord.Interaction, ephemeral: bool = False):
    """Category % breakdown of expenses this month."""
    await interaction.response.defer(ephemeral=ephemeral)
    user_id = str(interaction.user.id)
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
        await interaction.followup.send("Failed to fetch expense data.", ephemeral=True)
        return
    rows = resp.data or []
    if not rows:
        await interaction.followup.send("No expenses this month yet.", ephemeral=ephemeral)
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
    await interaction.followup.send(embed=embed, ephemeral=ephemeral)


async def _send_insights(interaction: discord.Interaction, ephemeral: bool = False):
    """Compare this month vs last month spending by category."""
    await interaction.response.defer(ephemeral=ephemeral)
    user_id = str(interaction.user.id)
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
        await interaction.followup.send("Failed to fetch insight data.", ephemeral=True)
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
        await interaction.followup.send("Not enough data to generate insights yet.", ephemeral=ephemeral)
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
    await interaction.followup.send(embed=embed, ephemeral=ephemeral)


async def _send_goals(interaction: discord.Interaction, ephemeral: bool = False):
    """Show all savings goals with progress bars."""
    await interaction.response.defer(ephemeral=ephemeral)
    user_id = str(interaction.user.id)
    try:
        resp = (
            supabase.table("goals")
            .select("name, target_amount, current_amount, deadline")
            .eq("user_id", user_id)
            .execute()
        )
    except Exception as e:
        print(e)
        await interaction.followup.send("Failed to fetch goals.", ephemeral=True)
        return
    goals = resp.data or []
    if not goals:
        await interaction.followup.send("No goals set. Use `/setgoal` to create one.", ephemeral=ephemeral)
        return
    embed = discord.Embed(title="🏆 Savings Goals", color=discord.Color.teal())
    for g in goals:
        current = float(g["current_amount"])
        target = float(g["target_amount"])
        bar = progress_bar(current, target)
        deadline_str = f" · Due {g['deadline']}" if g.get("deadline") else ""
        status = "✅ Complete!" if current >= target else f"₱{current:.2f} / ₱{target:.2f}{deadline_str}"
        embed.add_field(name=g["name"], value=f"{bar}  {status}", inline=False)
    await interaction.followup.send(embed=embed, ephemeral=ephemeral)


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
    await client.tree.sync()
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
                    "created_at": datetime.now(timezone.utc).isoformat(),
                }).execute()
                supabase.table("recurring").update({"last_run": today.isoformat()}).eq("id", row["id"]).execute()
                print(f"Auto-logged recurring '{row['description']}' for user {row['user_id']}")
            except Exception as e:
                print(f"Failed to log recurring {row['id']}: {e}")

# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

@client.tree.command(name="hello", description="Greet the bot.")
async def hello(interaction: discord.Interaction):
    embed = discord.Embed(
        title="Welcome to FinTrack! 👋",
        description=(
            "I'm your personal finance assistant.\n\n"
            "Use `/menu` to open an interactive dashboard,\n"
            "or type `/help` to see all available commands."
        ),
        color=discord.Color.blue()
    )
    await interaction.response.send_message(embed=embed)


@client.tree.command(name="help", description="Show all available commands.")
async def help_command(interaction: discord.Interaction):
    embed = discord.Embed(
        title='FinTrack — Command Guide',
        description='Use `/menu` for a fully interactive dashboard with pop-up forms.',
        color=discord.Color.blue()
    )
    embed.add_field(name='/menu', value='Open the interactive dashboard.', inline=False)
    embed.add_field(name='/expense', value='Log an expense via pop-up form.', inline=False)
    embed.add_field(name='/income', value='Log income via pop-up form.', inline=False)
    embed.add_field(name='/balance', value="Show this month's income, expenses, and balance.", inline=False)
    embed.add_field(name='/history', value='Show your last 10 transactions.', inline=False)
    embed.add_field(name='/breakdown', value="Category % breakdown of this month's expenses.", inline=False)
    embed.add_field(name='/insights', value='Compare this month vs last month by category.', inline=False)
    embed.add_field(name='/setbudget', value='Set (or update) a monthly spending limit for a category.', inline=False)
    embed.add_field(name='/budgets', value='View all budget limits with progress bars.', inline=False)
    embed.add_field(name='/deletebudget', value='Delete a budget category via dropdown.', inline=False)
    embed.add_field(name='/setgoal', value='Create a savings goal with a target and deadline.', inline=False)
    embed.add_field(name='/goals', value='View all savings goals and progress.', inline=False)
    embed.add_field(name='/contribute', value='Add money toward a savings goal.', inline=False)
    embed.add_field(name='/editgoal', value='Edit an existing savings goal via dropdown.', inline=False)
    embed.add_field(name='/deletegoal', value='Delete a savings goal via dropdown.', inline=False)
    embed.add_field(name='/setrecurring', value='Add a recurring weekly/monthly transaction.', inline=False)
    embed.add_field(name='/recurringlist', value='View all your recurring transactions.', inline=False)
    embed.add_field(name='/editrecurring', value='Edit a recurring transaction via dropdown.', inline=False)
    embed.add_field(name='/deleterecurring', value='Delete a recurring transaction via dropdown.', inline=False)
    embed.add_field(name='/delete', value='Delete a specific transaction via dropdown.', inline=False)
    embed.add_field(name='/export', value='Export all transactions as a CSV to your DMs.', inline=False)
    embed.add_field(name='/undo', value='Delete your most recent transaction.', inline=False)
    embed.add_field(name='/hello', value='Greet the bot.', inline=False)
    embed.add_field(name='/help', value='Show this help message.', inline=False)
    await interaction.response.send_message(embed=embed, ephemeral=True)


@client.tree.command(name="menu", description="Open the interactive FinTrack dashboard.")
async def menu(interaction: discord.Interaction):
    embed = discord.Embed(
        title="FinTrack Dashboard",
        description="Choose an action below:",
        color=discord.Color.blurple()
    )
    await interaction.response.send_message(embed=embed, view=MenuView())


@client.tree.command(name="expense", description="Log an expense via pop-up form.")
async def expense(interaction: discord.Interaction):
    await interaction.response.send_modal(ExpenseModal())


@client.tree.command(name="income", description="Log income via pop-up form.")
async def income(interaction: discord.Interaction):
    await interaction.response.send_modal(IncomeModal())


@client.tree.command(name="balance", description="Show this month's income, expenses, and balance.")
async def balance(interaction: discord.Interaction):
    await _send_balance(interaction)


@client.tree.command(name="history", description="Show your last 10 transactions.")
async def history(interaction: discord.Interaction):
    await _send_history(interaction)


@client.tree.command(name="setbudget", description="Set a monthly spending limit for a category.")
async def setbudget(interaction: discord.Interaction):
    await interaction.response.send_modal(SetBudgetModal())


@client.tree.command(name="budgets", description="View all budget limits with progress bars.")
async def budgets(interaction: discord.Interaction):
    await _send_budgets(interaction)


@client.tree.command(name="breakdown", description="Category % breakdown of this month's expenses.")
async def breakdown(interaction: discord.Interaction):
    await _send_breakdown(interaction)


@client.tree.command(name="insights", description="Compare this month vs last month by category.")
async def insights(interaction: discord.Interaction):
    await _send_insights(interaction)


@client.tree.command(name="delete", description="Delete a specific transaction via dropdown.")
async def delete_transaction(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    user_id = str(interaction.user.id)
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
        await interaction.followup.send("Failed to fetch your transactions.", ephemeral=True)
        return
    rows = resp.data or []
    if not rows:
        await interaction.followup.send("You have no transactions to delete.", ephemeral=True)
        return
    embed = discord.Embed(
        title="🗑️ Delete a Transaction",
        description="Select a transaction from the dropdown below:",
        color=discord.Color.orange(),
    )
    await interaction.followup.send(embed=embed, view=DeleteView(rows), ephemeral=True)


@client.tree.command(name="export", description="Export all transactions as a CSV to your DMs.")
async def export_transactions(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    user_id = str(interaction.user.id)
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
        await interaction.followup.send("Failed to fetch your transactions.", ephemeral=True)
        return
    rows = resp.data or []
    if not rows:
        await interaction.followup.send("No transactions to export.", ephemeral=True)
        return
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=["date", "type", "amount", "category", "description"])
    writer.writeheader()
    for row in rows:
        writer.writerow({
            "date": row["created_at"][:10] if row["created_at"] else "Unknown",
            "type": row["type"],
            "amount": row["amount"],
            "category": row["category"],
            "description": row["description"] or "",
        })
    output.seek(0)
    file = discord.File(fp=io.BytesIO(output.getvalue().encode()), filename="transactions.csv")
    try:
        await interaction.user.send("📎 Here's your transaction export:", file=file)
        await interaction.followup.send("✅ Sent your export to your DMs!", ephemeral=True)
    except discord.Forbidden:
        await interaction.followup.send("❌ I couldn't DM you. Please enable DMs from server members.", ephemeral=True)


@client.tree.command(name="setgoal", description="Create a savings goal with a target and deadline.")
async def setgoal(interaction: discord.Interaction):
    await interaction.response.send_modal(SetGoalModal())


@client.tree.command(name="goals", description="View all savings goals and progress.")
async def goals(interaction: discord.Interaction):
    await _send_goals(interaction)


@client.tree.command(name="contribute", description="Add money toward a savings goal.")
async def contribute(interaction: discord.Interaction):
    await interaction.response.send_modal(ContributeGoalModal())


@client.tree.command(name="setrecurring", description="Add a recurring weekly/monthly transaction.")
async def setrecurring(interaction: discord.Interaction):
    await interaction.response.send_modal(SetRecurringModal())


@client.tree.command(name="recurringlist", description="View all your recurring transactions.")
async def recurringlist(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    user_id = str(interaction.user.id)
    try:
        resp = supabase.table("recurring").select("*").eq("user_id", user_id).execute()
    except Exception as e:
        print(e)
        await interaction.followup.send("Failed to fetch recurring transactions.", ephemeral=True)
        return
    rows = resp.data or []
    if not rows:
        await interaction.followup.send("No recurring transactions set. Use `/setrecurring` to add one.", ephemeral=True)
        return
    embed = discord.Embed(title="🔁 Recurring Transactions", color=discord.Color.purple())
    for r in rows:
        sign = "+" if r["type"] == "income" else "-"
        last = f"Last run: {r['last_run']}" if r.get("last_run") else "Not run yet"
        embed.add_field(
            name=f"{r['type'].capitalize()} · {r['category']} · {sign}₱{float(r['amount']):.2f} ({r['frequency']})",
            value=f"{r['description'] or '—'} · {last}",
            inline=False,
        )
    await interaction.followup.send(embed=embed, ephemeral=True)


@client.tree.command(name="editrecurring", description="Edit an existing recurring transaction.")
async def editrecurring(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    user_id = str(interaction.user.id)
    try:
        resp = supabase.table("recurring").select("*").eq("user_id", user_id).execute()
    except Exception as e:
        print(e)
        await interaction.followup.send("Failed to fetch recurring transactions.", ephemeral=True)
        return
    rows = resp.data or []
    if not rows:
        await interaction.followup.send("No recurring transactions to edit.", ephemeral=True)
        return
    embed = discord.Embed(
        title="✏️ Edit Recurring Transaction",
        description="Select an entry to edit:",
        color=discord.Color.purple(),
    )
    await interaction.followup.send(embed=embed, view=RecurringEditView(rows), ephemeral=True)


@client.tree.command(name="deleterecurring", description="Delete a recurring transaction.")
async def deleterecurring(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    user_id = str(interaction.user.id)
    try:
        resp = supabase.table("recurring").select("*").eq("user_id", user_id).execute()
    except Exception as e:
        print(e)
        await interaction.followup.send("Failed to fetch recurring transactions.", ephemeral=True)
        return
    rows = resp.data or []
    if not rows:
        await interaction.followup.send("No recurring transactions to delete.", ephemeral=True)
        return
    embed = discord.Embed(
        title="🗑️ Delete Recurring Transaction",
        description="Select an entry to remove:",
        color=discord.Color.orange(),
    )
    await interaction.followup.send(embed=embed, view=RecurringDeleteView(rows), ephemeral=True)


@client.tree.command(name="editgoal", description="Edit an existing savings goal.")
async def editgoal(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    user_id = str(interaction.user.id)
    try:
        resp = supabase.table("goals").select("*").eq("user_id", user_id).execute()
    except Exception as e:
        print(e)
        await interaction.followup.send("Failed to fetch goals.", ephemeral=True)
        return
    rows = resp.data or []
    if not rows:
        await interaction.followup.send("No goals to edit.", ephemeral=True)
        return
    embed = discord.Embed(
        title="✏️ Edit Savings Goal",
        description="Select a goal to edit:",
        color=discord.Color.teal(),
    )
    await interaction.followup.send(embed=embed, view=GoalEditView(rows), ephemeral=True)


@client.tree.command(name="deletegoal", description="Delete a savings goal.")
async def deletegoal(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    user_id = str(interaction.user.id)
    try:
        resp = supabase.table("goals").select("*").eq("user_id", user_id).execute()
    except Exception as e:
        print(e)
        await interaction.followup.send("Failed to fetch goals.", ephemeral=True)
        return
    rows = resp.data or []
    if not rows:
        await interaction.followup.send("No goals to delete.", ephemeral=True)
        return
    embed = discord.Embed(
        title="🗑️ Delete Savings Goal",
        description="Select a goal to remove:",
        color=discord.Color.orange(),
    )
    await interaction.followup.send(embed=embed, view=GoalDeleteView(rows), ephemeral=True)


@client.tree.command(name="deletebudget", description="Delete a monthly budget for a category.")
async def deletebudget(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    user_id = str(interaction.user.id)
    try:
        resp = supabase.table("budgets").select("*").eq("user_id", user_id).execute()
    except Exception as e:
        print(e)
        await interaction.followup.send("Failed to fetch budgets.", ephemeral=True)
        return
    rows = resp.data or []
    if not rows:
        await interaction.followup.send("No budgets to delete.", ephemeral=True)
        return
    embed = discord.Embed(
        title="🗑️ Delete Budget",
        description="Select a budget to remove:",
        color=discord.Color.orange(),
    )
    await interaction.followup.send(embed=embed, view=BudgetDeleteView(rows), ephemeral=True)


@client.tree.command(name="undo", description="Delete your most recent transaction.")
async def undo(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    user_id = str(interaction.user.id)
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
        await interaction.followup.send("Failed to fetch your last transaction.", ephemeral=True)
        return

    if not resp.data:
        await interaction.followup.send("You have no transactions to undo.", ephemeral=True)
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
        await interaction.followup.send(embed=embed, ephemeral=True)
    except Exception as e:
        print(e)
        await interaction.followup.send("Failed to delete the transaction.", ephemeral=True)


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