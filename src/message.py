from typing import Optional
from datetime import datetime
from dataclasses import dataclass

"""{
   "id": 786944,
   "type": "message",
   "date": "2024-11-17T21:22:41",
   "date_unixtime": "1731874961",
   "edited": "2024-11-17T21:22:52",
   "edited_unixtime": "1731874972",
   "from": "Airat",
   "from_id": "user409474295",
   "reply_to_message_id": 786940,
   "text": "эх, а я вот в Мюнхене уже",
   "text_entities": [
    {
     "type": "plain",
     "text": "эх, а я вот в Мюнхене уже"
    }
   ],
   "reactions": [
     {
      "type": "emoji",
      "count": 1,
      "emoji": "❤",
      "recent": [
       {
        "from": "Alina",
        "from_id": "user1263460953",
        "date": "2024-11-17T21:22:52"
       }
      ]
     }
    ]
  },"""


# @dataclass
# class Reaction:
#     emoji: str
#     count: int


@dataclass
class Message:
    id: int
    from_: str
    text: str
    dt: datetime
    edited_dt: datetime | None = None
    reply_to_id: int | None = None
    reply_to: Optional["Message"] = None
    # reactions: list[Reaction] = field(default_factory=list)

    @classmethod
    def from_dict(cls, json_data: dict) -> "Message":
        return cls(
            id=json_data["id"],
            from_=json_data["from"],
            text=json_data["text"],
            dt=datetime.fromisoformat(json_data["date"]),
            edited_dt=datetime.fromisoformat(json_data["edited"])
            if json_data.get("edited")
            else None,
            reply_to_id=json_data.get("reply_to_message_id"),
        )
