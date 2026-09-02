import sys
import os
import uuid
import asyncio
from sqlalchemy import select

# Add the app directory to the path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.database import async_session_maker, engine
from app.models.ministry import Ministry

async def update_ministries():
    async with async_session_maker() as db:
        try:
            ministries_data = [
                {
                    "title": "Kingdom Gospel Ministry",
                    "ministry_key": "kingdom_gospel",
                    "description": "Our gospel ministry committed to winning individuals, cities, nations, and the world with the gospel of Jesus Christ. \n\n\"That in the dispensation of the fulness of times he might gather together in one all things in Christ, both which are in heaven, and which are on earth; even in him:\"\n— Ephesians 1:10 (KJV)",
                    "icon_name": "Globe2",
                    "is_active": True,
                    "is_featured": True,
                    "display_order": 1,
                    "activities": {
                        "teams": [
                            "Mission and outreach team (Matthew 28:18-19)",
                            "Prison evangelism team (Matthew 25:36)",
                            "Prostitute evangelism team (Luke 5:32)",
                            "Hospital evangelism team (Matthew 25:36)",
                            "Media evangelism team",
                            "Missionary and evangelism training: Taking the gospel of Christ into every corner to find the lost"
                        ],
                        "spiritual_ancestry": "Honoring Spiritual Ancestry: Acknowledging gospel fathers and mothers who preach and suffer for the gospel of Christ. (Hebrews 13:7)"
                    }
                },
                {
                    "title": "Mamlakah Worship Ministry",
                    "ministry_key": "worship",
                    "description": "Mamlakah is a Hebrew word meaning kingdom, dominion, reign or sovereignty. \n\n\"And hast made us unto our God kings and priests: and we shall reign on the earth.\"\n— Revelation 5:10 (KJV)\n\nMore Than a Song — it is an encounter experiencing heaven. Equipping and training singers and musicians for the glory of the King.",
                    "icon_name": "Music",
                    "is_active": True,
                    "is_featured": True,
                    "display_order": 2
                },
                {
                    "title": "Team Love Charity Ministry",
                    "ministry_key": "charity",
                    "description": "Demonstrating God's love in action through kids and family projects, city projects, youth projects, and elders projects.",
                    "icon_name": "Heart",
                    "is_active": True,
                    "is_featured": True,
                    "display_order": 3
                },
                {
                    "title": "Voice of the King Media Ministry",
                    "ministry_key": "media",
                    "description": "Our media team that uses technology to spread the gospel beyond the walls of the church. \n\n\"The LORD'S voice crieth unto the city, and the man of wisdom shall see thy name: hear ye the rod, and who hath appointed it.\"\n— Micah 6:9 (KJV)",
                    "icon_name": "Mic2",
                    "is_active": True,
                    "is_featured": True,
                    "display_order": 4
                },
                {
                    "title": "Kingdom Family Ministry",
                    "ministry_key": "family",
                    "description": "Committed to raising a generation that manifests the standards and culture of heaven within their everyday lives. \n\nIncludes: Ecclesia, Kingdom Men's, Kingdom Women's, Kingdom Marriage, Kingdom Youth, and Kingdom Kids.",
                    "icon_name": "Home",
                    "is_active": True,
                    "is_featured": True,
                    "display_order": 5,
                    "activities": {
                        "sub_families": [
                            "Ecclesia (Ephesians 1:23)",
                            "Kingdom Family (Genesis 1:27)",
                            "Kingdom Men's: Walking in God's design and purpose",
                            "Kingdom Women's: Walking in God's design and purpose",
                            "Kingdom Marriage: Kingdom culture begins in a family",
                            "Kingdom Youth: Raising world changers living for Christ",
                            "Kingdom Kids: Nurturing children to live in His love and carry His presence"
                        ]
                    }
                },
                {
                    "title": "Kingdom Reigners",
                    "ministry_key": "leaders",
                    "description": "Our leaders ministry committed to raising kingdom leaders who lead in the body of Christ and in the secular sector according to their God-given assignment. \n\n\"Ye are the light of the world. A city that is set on an hill cannot be hid.\"\n— Matthew 5:14 (KJV)",
                    "icon_name": "Zap",
                    "is_active": True,
                    "is_featured": True,
                    "display_order": 6
                }
            ]
            
            for data in ministries_data:
                stmt = select(Ministry).filter(Ministry.ministry_key == data["ministry_key"])
                result = await db.execute(stmt)
                ministry = result.scalar_one_or_none()
                
                if ministry:
                    for key, value in data.items():
                        setattr(ministry, key, value)
                else:
                    ministry = Ministry(**data)
                    db.add(ministry)
            
            await db.commit()
            print("Ministries updated successfully!")
        except Exception as e:
            await db.rollback()
            print(f"Error updating ministries: {e}")
        finally:
            await db.close()

if __name__ == "__main__":
    asyncio.run(update_ministries())
