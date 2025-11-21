import asyncio
from app import business_logic as bl


async def main():
    result = await bl.order_status(
        order_number="7583ll",
        phone="+9163225519",
        call_sid="call_sid"
    )
    print(result)


if __name__ == "__main__":
    asyncio.run(main())
