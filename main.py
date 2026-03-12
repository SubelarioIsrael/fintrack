import discord
from discord.ext import commands
from dotenv import load_dotenv
from supabase import create_client
from datetime import datetime, timezone
import os
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
    embed.add_field(name='!setbudget', value='Set a monthly spending limit for a category.', inline=False)
    embed.add_field(name='!budgets', value='View all budget limits with spending progress bars.', inline=False)
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