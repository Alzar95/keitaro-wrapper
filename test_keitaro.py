import asyncio
from app.keitaro import get_keitaro_client

async def main():
    client = get_keitaro_client()
    campaigns = await client.list_campaigns(limit=5)
    print(f"Campaigns: {len(campaigns)}")
    for c in campaigns[:3]:
        print(c.get("id"), c.get("name"))
    if campaigns:
        streams = await client.list_streams(campaigns[0]["id"])
        print(f"Streams in campaign {campaigns[0]['id']}: {len(streams)}")

asyncio.run(main())