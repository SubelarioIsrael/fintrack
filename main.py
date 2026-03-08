import discord
from discord.ext import commands
from dotenv import load_dotenv
from supabase import create_client
import os

load_dotenv()

url = os.getenv("SUPABASE_URL")
key = os.getenv("SUPABASE_KEY")

supabase = create_client(url, key)

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


class MenuView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=120)

    @discord.ui.button(label="Log Expense", style=discord.ButtonStyle.red, emoji="💸")
    async def log_expense(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(ExpenseModal())

    @discord.ui.button(label="Log Income", style=discord.ButtonStyle.green, emoji="💰")
    async def log_income(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(IncomeModal())

    @discord.ui.button(label="Check Balance", style=discord.ButtonStyle.blurple, emoji="📊")
    async def check_balance(self, interaction: discord.Interaction, button: discord.ui.Button):
        user_id = str(interaction.user.id)

        try:
            income_resp = (
                supabase.table("transactions")
                .select("amount")
                .eq("user_id", user_id)
                .eq("type", "income")
                .execute()
            )
            income_list = income_resp.data if income_resp.data else []
        except Exception as e:
            print(e)
            await interaction.response.send_message("Failed to fetch income data.", ephemeral=True)
            return

        try:
            expense_resp = (
                supabase.table("transactions")
                .select("amount")
                .eq("user_id", user_id)
                .eq("type", "expense")
                .execute()
            )
            expense_list = expense_resp.data if expense_resp.data else []
        except Exception as e:
            print(e)
            await interaction.response.send_message("Failed to fetch expense data.", ephemeral=True)
            return

        total_income = sum(i["amount"] for i in income_list) if income_list else 0
        total_expense = sum(i["amount"] for i in expense_list) if expense_list else 0
        balance_val = total_income - total_expense

        color = discord.Color.green() if balance_val >= 0 else discord.Color.red()
        embed = discord.Embed(title="Your Balance Summary", color=color)
        embed.add_field(name="Total Income", value=f"₱{total_income:.2f}", inline=False)
        embed.add_field(name="Total Expenses", value=f"₱{total_expense:.2f}", inline=False)
        embed.add_field(name="Balance", value=f"₱{balance_val:.2f}", inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

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
    embed.add_field(name='!menu', value='Open the interactive dashboard with buttons.', inline=False)
    embed.add_field(name='!hello', value='Greet the bot.', inline=False)
    embed.add_field(name='!expense', value='Opens a pop-up form to log an expense.', inline=False)
    embed.add_field(name='!income', value='Opens a pop-up form to log income.', inline=False)
    embed.add_field(name='!balance', value='Show your income, expenses, and balance.', inline=False)
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
    user_id = str(ctx.author.id)

    try:
        income_resp = (
            supabase.table("transactions")
            .select("amount")
            .eq("user_id", user_id)
            .eq("type", "income")
            .execute()
        )
        income_list = income_resp.data if income_resp.data else []
    except Exception as e:
        print(e)
        await ctx.send("Failed to fetch income data.")
        return

    try:
        expense_resp = (
            supabase.table("transactions")
            .select("amount")
            .eq("user_id", user_id)
            .eq("type", "expense")
            .execute()
        )
        expense_list = expense_resp.data if expense_resp.data else []
    except Exception as e:
        print(e)
        await ctx.send("Failed to fetch expense data.")
        return

    total_income = sum(i["amount"] for i in income_list) if income_list else 0
    total_expense = sum(i["amount"] for i in expense_list) if expense_list else 0
    balance_val = total_income - total_expense

    color = discord.Color.green() if balance_val >= 0 else discord.Color.red()
    embed = discord.Embed(title="Your Balance Summary", color=color)
    embed.add_field(name="Total Income", value=f"₱{total_income:.2f}", inline=False)
    embed.add_field(name="Total Expenses", value=f"₱{total_expense:.2f}", inline=False)
    embed.add_field(name="Balance", value=f"₱{balance_val:.2f}", inline=False)
    await ctx.send(embed=embed)


client.run(os.getenv('BOT_TOKEN'))