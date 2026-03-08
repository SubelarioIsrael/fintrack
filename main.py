import discord
from discord.ext import commands
from dotenv import load_dotenv
from supabase import create_client
import os

load_dotenv()

url = os.getenv("SUPABASE_URL")
key = os.getenv("SUPABASE_KEY")

supabase = create_client(url, key)

intents = discord.Intents.default()
intents.message_content = True

client = commands.Bot(command_prefix='!', intents=intents, help_command=None)

@client.event
async def on_ready():
    print('FinTrack is ready to use!')
    print('------------------------------')

@client.command()
async def hello(ctx):
    await ctx.send('Hello! I am FinTrack, your personal finance assistant. How can I help you today?')


@client.command(name='help')
async def help_command(ctx):
    help_text = (
        "Available commands:\n"
        "!hello - Greet the bot.\n"
        "!expense <amount> <category> <description> - Record an expense.\n"
        "!income <amount> <category> <description> - Record income.\n"
        "!balance - Show your current balance.\n"
        "!help - Show this help message."
    )
    await ctx.send(help_text)

@client.command()
async def expense(ctx, amount: float, category: str, *, description: str):

    user_id = str(ctx.author.id)

    data = {
        "user_id": user_id,
        "type": "expense",
        "amount": amount,
        "category": category,
        "description": description
    }

    try:
        supabase.table("transactions").insert(data).execute()
        await ctx.send(f"Expense recorded: {amount} | {category}")
    except Exception as e:
        print(e)
        await ctx.send("Failed to record expense.")

@client.command()
async def income(ctx, amount: float, category: str, *, description: str):

    user_id = str(ctx.author.id)

    data = {
        "user_id": user_id,
        "type": "income",
        "amount": amount,
        "category": category,
        "description": description
    }

    try:
        supabase.table("transactions").insert(data).execute()
        await ctx.send(f"Income recorded: {amount} | {category}")
    except Exception as e:
        print(e)
        await ctx.send("Failed to record income.")

@client.command()
async def balance(ctx):

    user_id = str(ctx.author.id)

    try:
        income_resp = supabase.table("transactions") \
            .select("amount") \
            .eq("user_id", user_id) \
            .eq("type", "income") \
            .execute()
        income_list = income_resp.data if income_resp.data else []
    except Exception as e:
        print(e)
        await ctx.send("Failed to fetch income data.")
        income_list = []

    try:
        expense_resp = supabase.table("transactions") \
            .select("amount") \
            .eq("user_id", user_id) \
            .eq("type", "expense") \
            .execute()
        expense_list = expense_resp.data if expense_resp.data else []
    except Exception as e:
        print(e)
        await ctx.send("Failed to fetch expense data.")
        expense_list = []

    total_income = sum(i["amount"] for i in income_list) if income_list else 0
    total_expense = sum(i["amount"] for i in expense_list) if expense_list else 0

    balance_val = total_income - total_expense

    await ctx.send(
        f"Income: {total_income}\nExpenses: {total_expense}\nBalance: {balance_val}"
    )

client.run(os.getenv('BOT_TOKEN'))