import json
import datetime
from typing import Literal, Callable
from pathlib import Path
from collections import defaultdict, Counter

import numpy as np
import plotly.graph_objects as go

from src.message import Message, reply_chain


GroupbyKeys = Literal["day", "week", "month"]


class Chat:
    def __init__(self, exported_file: Path):
        self.id_name = exported_file.stem
        with exported_file.open(encoding="utf-8") as f:
            self.data = json.load(f)
        self.chat_with = self.data["name"]
        if self.data["type"] != "personal_chat":
            raise NotImplementedError("Only personal chats are supported")
        messages_map = {
            (this_msg := Message.from_dict(msg)).id: this_msg
            for msg in self.data["messages"]
            if msg["type"] == "message"
        }
        for msg in messages_map.values():
            if (
                msg.reply_to_id is not None
                and (replied_to := messages_map.get(msg.reply_to_id)) is not None
            ):
                msg.reply_to = replied_to
        self.messages = list(messages_map.values())

    def __repr__(self) -> str:
        return f"Chat({self.chat_with}; {len(self.messages)} messages)"

    def groupby(
        self, key: GroupbyKeys
    ) -> defaultdict[datetime.date | datetime.datetime, list[Message]]:
        """Group messages by day, week, or month."""
        KEYMAP: dict[
            GroupbyKeys,
            Callable[[Message], datetime.date | datetime.datetime],
        ] = {
            "day": lambda x: x.dt.date(),
            "week": lambda x: (x.dt - datetime.timedelta(days=x.dt.weekday())).date(),
            "month": lambda x: x.dt.date().replace(day=1),
        }
        grouped = defaultdict(list)
        for msg in self.messages:
            grouped[KEYMAP[key](msg)].append(msg)
        return grouped

    def get_other_msg_types(self) -> Counter:
        types = Counter()
        for message in self.messages:
            types.update(message.other_text_entity_types)
        return types

    def get_message_lengths(self) -> defaultdict[str, list[int]]:
        message_lens = defaultdict(list)
        for message in self.messages:
            if message.text:
                message_lens[message.from_].append(len(message.text))
        return message_lens

    def get_reply_chains(self) -> list[list[Message]]:
        msg_reply_chains = []
        for msg in reversed(self.messages):
            rc = reply_chain(msg)
            if len(rc) > 1:
                msg_reply_chains.append(rc)
        return msg_reply_chains

    def display_longest_reply_chain(self) -> None:
        msg_reply_chains = self.get_reply_chains()
        longest_chain = max(msg_reply_chains, key=len)
        for i, msg in enumerate(reversed(longest_chain)):
            print("  " * i, msg)

    def get_trace_messages_by(
        self, groupby_key: GroupbyKeys, messages_include
    ) -> go.Scatter:
        """Get a line chart trace with the number of messages by day/week/month."""
        if isinstance(messages_include, str):
            messages_include = [messages_include]
        group = self.groupby(groupby_key)
        days = list(group.keys())
        n_messages_lst = [
            sum(
                messages_include is None
                or any(word in msg.text for word in messages_include)
                for msg in day_msgs
            )
            for day_msgs in group.values()
        ]
        return go.Scatter(
            x=days,
            y=n_messages_lst,
            mode="lines+markers",
            line_shape="spline",
            name=self.chat_with,
        )


class Chats:
    def __init__(self, your_name: str, chats: list[Chat]):
        self.your_name = your_name
        chats.sort(key=lambda chat: len(chat.messages), reverse=True)
        self.chats = {chat.id_name: chat for chat in chats}

    def __repr__(self) -> str:
        return f"Chats({len(self.chats)} chats)"

    def __iter__(self):
        return iter(self.chats.values())

    def __getitem__(self, key: str) -> Chat:
        return self.chats[key]

    def fig_bar_chart(
        self,
    ) -> go.Figure:
        """Plot grouped bar chart showing mean message length with error bars (±3 SE)."""

        chat_to_message_lengths = {
            chat.chat_with: chat.get_message_lengths() for chat in self
        }

        fig = go.Figure()

        chat_names = []
        medians = ([], [])
        se_values = ([], [])

        for chat_name, message_lengths in chat_to_message_lengths.items():
            for sender, lengths in message_lengths.items():
                idx = 0 if sender == self.your_name else 1
                lengths = np.array(lengths)
                median = np.median(lengths)
                stdev = np.std(lengths)
                se = 3 * stdev / np.sqrt(len(lengths))
                if idx == 0:
                    chat_names.append(chat_name)
                medians[idx].append(median)
                se_values[idx].append(se)

        print(chat_names, medians, se_values)

        fig = go.Figure()

        fig.add_trace(
            go.Bar(
                name="me",
                x=chat_names,
                y=medians[0],
                error_y=dict(
                    type="data",
                    array=se_values[0],
                    visible=True,
                ),
            )
        )

        fig.add_trace(
            go.Bar(
                name="them",
                x=chat_names,
                y=medians[1],
                error_y=dict(
                    type="data",
                    array=se_values[1],
                    visible=True,
                ),
            )
        )

        fig.update_layout(
            barmode="group",
            template="plotly_dark",
            legend=dict(
                orientation="h",
                yanchor="top",
                y=1.1,
                xanchor="center",
                x=0.5,
            ),
        )

        fig.update_xaxes(title_text="Chat")
        fig.update_yaxes(title_text="Median message length ± 3 standard errors")

        return fig

    def fig_bar(
        self,
        messages_include: str | list[str] | None = None,
        is_percentage: bool = False,
        split_by_sender: bool = False,
    ) -> go.Figure:
        """Plot a bar chart with the number of messages (or percentage) in each chat.
        Optionally, include only messages that contain a specific string.
        """
        chat_names = []
        vals = []
        if isinstance(messages_include, str):
            messages_include = [messages_include]
        if split_by_sender:
            senders = []
            colors = []
            for chat in self:
                total_messages = len(chat.messages)
                n_messages_you = sum(
                    1
                    for msg in chat.messages
                    if msg.from_ == self.your_name
                    and (
                        messages_include is None
                        or any(word in msg.text for word in messages_include)
                    )
                )
                n_messages_other = sum(
                    1
                    for msg in chat.messages
                    if msg.from_ != self.your_name
                    and (
                        messages_include is None
                        or any(word in msg.text for word in messages_include)
                    )
                )
                chat_names.extend([chat.chat_with, chat.chat_with])
                senders.extend(["me", ""])
                colors.extend(["#1f77b4", "#ff7f0e"])
                vals.extend(
                    [
                        n_messages_you / total_messages
                        if is_percentage
                        else n_messages_you,
                        n_messages_other / total_messages
                        if is_percentage
                        else n_messages_other,
                    ]
                )
            fig = go.Figure(
                go.Bar(
                    x=chat_names,
                    y=vals,
                    marker_color=colors,
                    name="Messages per sender",
                    text=senders,
                    textposition="auto",
                )
            )
        else:
            for chat in self:
                total_messages = len(chat.messages)
                n_messages = sum(
                    1
                    for msg in chat.messages
                    if messages_include is None
                    or any(word in msg.text for word in messages_include)
                )
                chat_names.append(chat.chat_with)
                vals.append(
                    n_messages / total_messages if is_percentage else n_messages
                )
            fig = go.Figure(
                go.Bar(
                    x=chat_names,
                    y=vals,
                )
            )

        fig.update_layout(
            margin=dict(l=10, r=10, t=10, b=10),
            template="plotly_dark",
            yaxis_title=f"{'Number' if not is_percentage else 'Percentage'} of messages"
            + (f" containing '{messages_include}'" if messages_include else ""),
            barmode="group" if split_by_sender else "relative",
        )
        return fig

    def fig_messages_by(
        self, groupby_key: GroupbyKeys, messages_include: str | list[str] | None = None
    ) -> go.Figure:
        """Plot a line chart with the number of messages by day."""
        fig = go.Figure()
        if isinstance(messages_include, str):
            messages_include = [messages_include]
        for chat in self:
            trace = chat.get_trace_messages_by(groupby_key, messages_include)
            fig.add_trace(trace)
        fig.update_layout(
            margin=dict(l=10, r=10, t=10, b=10),
            template="plotly_dark",
        )
        fig.update_xaxes(title_text=groupby_key.capitalize())
        fig.update_yaxes(title_text=f"Number of messages by {groupby_key}")
        return fig

    def fig_other_message_types(self) -> go.Figure:
        """Plot a stacked bar chart of other message types for each chat."""
        fig = go.Figure()
        data = {chat.chat_with: chat.get_other_msg_types() for chat in self}
        all_types = set()
        for types in data.values():
            all_types.update(types.keys())

        visible_types = {
            "code",
            "pre",
            "blockquote",
            "spoiler",
        }

        for msg_type in all_types:
            fig.add_trace(
                go.Bar(
                    x=list(data.keys()),
                    y=[data[person].get(msg_type, 0) for person in data.keys()],
                    name=msg_type,
                    visible=True if msg_type in visible_types else "legendonly",
                )
            )
        fig.update_layout(
            margin=dict(l=10, r=10, t=30, b=10),
            template="plotly_dark",
            barmode="stack",
            title="Stacked Bar Chart of Message Types per Chat",
            xaxis_title="Chat Partner",
            yaxis_title="Number of Messages",
            legend_title="Message Type",
        )
        return fig
