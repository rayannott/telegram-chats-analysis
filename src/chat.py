import json
import datetime
import time
import warnings
import multiprocessing
from typing import Literal, Callable
from itertools import pairwise
from statistics import median
from pathlib import Path
from collections import defaultdict, Counter

import numpy as np
import plotly.graph_objects as go

from src.message import Message, reply_chain


GroupbyKeys = Literal["day", "week", "month"]


class Chat:
    @staticmethod
    def _build_messages(data: dict) -> list[Message]:
        messages_map = {
            (this_msg := Message.from_dict(msg)).id: this_msg
            for msg in data["messages"]
            if msg["type"] == "message"
        }
        for msg in messages_map.values():
            if (
                msg.reply_to_id is not None
                and (replied_to := messages_map.get(msg.reply_to_id)) is not None
            ):
                msg.reply_to = replied_to
        return list(messages_map.values())

    def __init__(self, exported_file: Path):
        t0 = time.perf_counter()
        self.id_name = exported_file.stem
        with exported_file.open(encoding="utf-8") as f:
            data = json.load(f)

        participant_id_map = {
            _from_id: msg.get("from")
            for msg in data["messages"]
            if (_from_id := msg.get("from_id")) is not None
        }
        if data["type"] != "personal_chat" or len(participant_id_map) != 2:
            raise NotImplementedError(
                f"Only personal chats are supported ({list(participant_id_map.keys())})"
            )
        chat_with_user_id: str = f"user{data['id']}"
        self.chat_with: str = data["name"]
        if self.chat_with != (upd_name := participant_id_map[chat_with_user_id]):
            warnings.warn(f"Chat name mismatch: {self.chat_with} vs {upd_name}")
            self.chat_with = upd_name

        self.messages = self._build_messages(data)
        self.you: str = next(
            msg.from_ for msg in self.messages if msg.from_ != self.chat_with
        )
        print(f"[{time.perf_counter() - t0:.2f}s] {self}")

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

    def get_waiting_times(self) -> defaultdict[str, list[float]]:
        waiting_times = defaultdict(list)

        for m1, m2 in pairwise(self.messages):
            if m1.from_ != m2.from_:
                tot_sec = (m2.dt - m1.dt).total_seconds()
                waiting_times[m1.from_].append(tot_sec)

        return waiting_times

    def display_longest_reply_chain(self) -> None:
        msg_reply_chains = self.get_reply_chains()
        longest_chain = max(msg_reply_chains, key=len)
        for i, msg in enumerate(reversed(longest_chain)):
            print("  " * i, msg)

    def get_reaction_counters(self) -> tuple[Counter[str], Counter[str]]:
        me, them = "", ""
        for m in self.messages:
            for react in m.reactions:
                for reactor, _ in react.from_when:
                    if reactor == self.you:
                        me += react.emoji
                    else:
                        them += react.emoji
        return Counter(me), Counter(them)

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
                or any(word.lower() in msg.text.lower() for word in messages_include)
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
    @staticmethod
    def _load_chats(from_files: list[Path]) -> list[Chat]:
        return [Chat(file) for file in from_files]

    @staticmethod
    def _load_chats_multi(from_files: list[Path]) -> list[Chat]:
        with multiprocessing.Pool(processes=multiprocessing.cpu_count()) as pool:
            chats = pool.map(Chat, from_files)
        return chats

    def __init__(self, chats_directory: Path, use_multiproc: bool = True):
        self.chats_dir = chats_directory
        chats_files = list(self.chats_dir.glob("*.json"))
        print(f"Found {len(chats_files)} chat files")
        chats = (
            self._load_chats_multi(chats_files)
            if use_multiproc
            else self._load_chats(chats_files)
        )
        chats.sort(key=lambda chat: len(chat.messages), reverse=True)
        self.chats = {chat.id_name: chat for chat in chats}
        your_names = [chat.you for chat in chats]
        assert (
            len(set(your_names)) == 1
        ), f"Some chats have different 'your_name' values: {your_names}"
        self.your_name = your_names[0]

    def __repr__(self) -> str:
        return f"Chats({len(self.chats)} chats)"

    def __iter__(self):
        return iter(self.chats.values())

    def __getitem__(self, key: str) -> Chat:
        return self.chats[key]

    def fig_waiting_times(self, threshold_median: float = 100.0) -> go.Figure:
        """Plot grouped bar chart showing mean waiting time between messages."""
        chat_to_waiting_times = {
            chat.chat_with: chat.get_waiting_times() for chat in self
        }

        fig = go.Figure()

        chat_names = []
        medians = ([], [])

        for chat_name, waiting_times in chat_to_waiting_times.items():
            for sender, times in waiting_times.items():
                idx = 0 if sender == self.your_name else 1
                mdn = median(times)
                median_ok = mdn < threshold_median
                if idx == 0 and median_ok:
                    chat_names.append(chat_name)
                if median_ok:
                    medians[idx].append(mdn)

        fig = go.Figure()

        fig.add_trace(
            go.Bar(
                name="me",
                x=chat_names,
                y=medians[0],
            )
        )

        fig.add_trace(
            go.Bar(
                name="them",
                x=chat_names,
                y=medians[1],
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
            title="Median waiting time between messages when switching sender",
        )

        fig.update_xaxes(title_text="Chat")
        fig.update_yaxes(title_text="Median waiting time (sec)")

        return fig

    def fig_messages_by_time_of_day(self, normalize: bool = False) -> go.Figure:
        """Plot a line chart with the number of messages by time of day."""
        by_time_of_day_by_chat = defaultdict(lambda: defaultdict(int))
        for chat_id, chat in self.chats.items():
            for message in chat.messages:
                by_time_of_day_by_chat[chat_id][message.dt.hour] += 1

        fig = go.Figure()
        for chat_id, by_time_of_day in by_time_of_day_by_chat.items():
            times_, messages_ = zip(*sorted(by_time_of_day.items()))
            if normalize:
                tot_msgs = sum(messages_)
                messages_ = [val / tot_msgs for val in messages_]
            fig.add_trace(
                go.Scatter(
                    x=times_,
                    y=messages_,
                    mode="lines+markers",
                    line_shape="spline",
                    name=self[chat_id].chat_with,
                )
            )
        fig.update_layout(
            title="Messages by time of day" + (" (normalized)" if normalize else ""),
            xaxis_title="Hour",
            yaxis_title="Number of messages",
            template="plotly_dark",
        )
        return fig

    def fig_message_length_statistics(self) -> go.Figure:
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
            title="Mean message length with error bars (±3 SE)",
        )

        fig.update_xaxes(title_text="Chat")
        fig.update_yaxes(title_text="Message length")

        return fig

    def fig_total_and_most_common_reactions(self) -> go.Figure:
        chat_names = []
        n_reactions = ([], [])
        most_common = ([], [])

        for chat in self:
            me_cnt, them_cnt = chat.get_reaction_counters()
            chat_names.append(chat.chat_with)
            n_reactions[0].append(sum(me_cnt.values()))
            n_reactions[1].append(sum(them_cnt.values()))
            me_emojis = "".join(emj for emj, _ in me_cnt.most_common(3))
            them_emojis = "".join(emj for emj, _ in them_cnt.most_common(3))
            most_common[0].append(me_emojis)
            most_common[1].append(them_emojis)

        fig = go.Figure()

        fig.add_trace(
            go.Bar(
                name="me",
                x=chat_names,
                y=n_reactions[0],
                text=most_common[0],
                textposition="outside",
            )
        )

        fig.add_trace(
            go.Bar(
                name="them",
                x=chat_names,
                y=n_reactions[1],
                text=most_common[1],
                textposition="outside",
            )
        )

        fig.update_layout(
            barmode="group",
            template="plotly_dark",
            legend=dict(orientation="h", yanchor="top", y=1.1, xanchor="left", x=0.1),
            title="Total number of reactions per chat and three most common reactions",
        )
        fig.update_xaxes(title_text="Chat")
        fig.update_yaxes(title_text="Number of reactions")

        return fig

    def display_most_common_reactions(self, n_most_common: int = 5) -> None:
        for chat in self:
            me_cnt, them_cnt = chat.get_reaction_counters()
            me_emojis = "".join(emj for emj, _ in me_cnt.most_common(n_most_common))
            them_emojis = "".join(emj for emj, _ in them_cnt.most_common(n_most_common))
            print(
                f"""{chat.chat_with}: 
    {me_emojis} (you) vs {them_emojis} (them) (total reactions: {sum(me_cnt.values())} vs {sum(them_cnt.values())})"""
            )

    def fig_total_number_of_messages(
        self,
        messages_include: str | list[str] | None = None,
        is_percentage: bool = False,
    ) -> go.Figure:
        """Plot a bar chart with the number of messages (or percentage) in each chat.
        Optionally, include only messages that contain a specific string.
        """
        chat_names = []
        vals = []
        if isinstance(messages_include, str):
            messages_include = [messages_include]
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
                    or any(
                        word.lower() in msg.text.lower() for word in messages_include
                    )
                )
            )
            n_messages_other = sum(
                1
                for msg in chat.messages
                if msg.from_ != self.your_name
                and (
                    messages_include is None
                    or any(
                        word.lower() in msg.text.lower() for word in messages_include
                    )
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

        fig.update_layout(
            margin=dict(l=10, r=10, t=30, b=10),
            template="plotly_dark",
            yaxis_title=f"{'Number' if not is_percentage else 'Percentage'} of messages",
            barmode="group",
            title=f"{'Number' if not is_percentage else 'Percentage'} of messages"
            + (
                (" containing " + ", ".join(messages_include))
                if messages_include and any(messages_include)
                else ""
            ),
        )
        return fig

    def fig_messages_vs_time(
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
            margin=dict(l=10, r=10, t=30, b=10),
            template="plotly_dark",
            title=f"Number of messages by {groupby_key}",
        )
        fig.update_xaxes(title_text=groupby_key.capitalize())
        fig.update_yaxes(title_text="Messages")
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
            title="Message modifier types per chat",
            xaxis_title="Chat",
            yaxis_title="Number of Messages",
            legend_title="Modifier Type",
        )
        return fig
