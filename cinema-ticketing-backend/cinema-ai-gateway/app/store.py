"""Redis-backed conversations, account restoration, leases, limits and feedback."""

import json
import secrets
import time
import uuid
from dataclasses import asdict, dataclass
from typing import Any, Literal

from fastapi import HTTPException
from redis.asyncio import Redis

from app.config import AUTH_REDIS_URL, MAX_STREAMS, REDIS_PREFIX, REDIS_URL
from app.feedback import MAX_SNAPSHOTS, SNAPSHOT_TTL, Snapshot

ANONYMOUS_TTL = 86400
ACCOUNT_TTL = 30 * 86400
MAX_SESSIONS = 2000
LEASE_SECONDS = 120
ChatChannel = Literal["dify", "agent"]

RATE_SCRIPT = """
local t=redis.call('TIME'); local now=t[1]*1000+math.floor(t[2]/1000)
redis.call('ZREMRANGEBYSCORE',KEYS[1],'-inf',now-60000)
if redis.call('ZCARD',KEYS[1])>=tonumber(ARGV[1]) then return 0 end
redis.call('ZADD',KEYS[1],now,ARGV[2]); redis.call('PEXPIRE',KEYS[1],65000); return 1
"""
ACQUIRE_SCRIPT = """
local t=redis.call('TIME'); local now=tonumber(t[1])
redis.call('ZREMRANGEBYSCORE',KEYS[2],'-inf',now)
if redis.call('EXISTS',KEYS[3])==0 then return 3 end
if ARGV[4]~='0' and redis.call('GET',KEYS[4])~=ARGV[5] then return 3 end
if redis.call('EXISTS',KEYS[1])==1 then return 0 end
if redis.call('ZCARD',KEYS[2])>=tonumber(ARGV[2]) then return 1 end
redis.call('SET',KEYS[1],ARGV[1],'EX',ARGV[3])
redis.call('ZADD',KEYS[2],now+tonumber(ARGV[3]),ARGV[1]); return 2
"""
RELEASE_SCRIPT = """
if redis.call('GET',KEYS[1])==ARGV[1] then redis.call('DEL',KEYS[1]) end
redis.call('ZREM',KEYS[2],ARGV[1]); return 1
"""
CREATE_SCRIPT = """
local t=redis.call('TIME'); local now=tonumber(t[1])
redis.call('ZREMRANGEBYSCORE',KEYS[1],'-inf',now)
if redis.call('ZCARD',KEYS[1])>=tonumber(ARGV[4]) then return 0 end
redis.call('HSET',KEYS[2],'chat_id',ARGV[1],'owner_id',ARGV[2],'conversation_id','','task_id','')
redis.call('EXPIRE',KEYS[2],ARGV[3]); redis.call('ZADD',KEYS[1],now+tonumber(ARGV[3]),ARGV[1]); return 1
"""
SNAPSHOT_SCRIPT = """
local t=redis.call('TIME'); local now=tonumber(t[1])
redis.call('ZREMRANGEBYSCORE',KEYS[1],'-inf',now)
redis.call('SET',KEYS[2],ARGV[2],'EX',ARGV[3]); redis.call('ZADD',KEYS[1],now+tonumber(ARGV[3]),ARGV[1])
local count=redis.call('ZCARD',KEYS[1])-tonumber(ARGV[4])
if count>0 then
  local old=redis.call('ZRANGE',KEYS[1],0,count-1)
  for _,id in ipairs(old) do redis.call('DEL',ARGV[5]..id); redis.call('ZREM',KEYS[1],id) end
end
return 1
"""


@dataclass
class Session:
    """Trusted Redis conversation plus the current tab's verified login binding."""

    chat_id: str
    owner_id: int = 0
    conversation_id: str = ""
    task_id: str = ""
    browser_key: str = ""
    auth_token: str = ""
    lease: str = ""

    @property
    def ttl(self) -> int:
        """Retain account history longer than anonymous browser history."""
        return ACCOUNT_TTL if self.owner_id else ANONYMOUS_TTL


class ConversationStore:
    """No process-local state determines identity, ownership, limits or exclusivity."""

    def __init__(self, channel: ChatChannel) -> None:
        """Keep all conversation data in a provider-specific Redis namespace.

        登录身份仍由 Java 共享会话校验；聊天历史、账号活跃指针、浏览器绑定、
        生成租约、取消标记、反馈和 Dify 编号均不跨渠道读取。旧混合会话不导入。
        """
        if channel not in ("dify", "agent"):
            raise ValueError("Unknown chat channel")
        self.channel = channel
        self.prefix = f"{REDIS_PREFIX}{channel}:"
        self.streams_key = REDIS_PREFIX + "streams"
        options = {
            "decode_responses": True,
            "socket_connect_timeout": 3,
            "socket_timeout": 5,
            "max_connections": 128,
            "health_check_interval": 30,
        }
        self.redis = Redis.from_url(REDIS_URL, **options)
        self.auth = Redis.from_url(AUTH_REDIS_URL, **options)

    def key(self, name: str) -> str:
        """Keep AI data under its own namespace in the existing Redis database."""
        return self.prefix + name

    async def close(self) -> None:
        """Release both connection pools at worker shutdown."""
        await self.redis.aclose()
        await self.auth.aclose()

    async def identity(self, token: str) -> int:
        """Verify Java's shared login session without a Java request per chat turn."""
        try:
            uuid.UUID(token)
        except (ValueError, AttributeError) as exc:
            raise HTTPException(401, "登录已过期，请重新登录", headers={"X-Auth-Expired": "1"}) from exc
        values = await self.auth.hgetall("auth:session:" + token)
        if not values.get("userId", "").isdigit():
            raise HTTPException(401, "登录已过期，请重新登录", headers={"X-Auth-Expired": "1"})
        return int(values["userId"])

    async def load(self, chat_id: str) -> Session | None:
        """Load one shared conversation; nonexistent IDs grant no access."""
        values = await self.redis.hgetall(self.key("session:" + chat_id))
        if not values:
            return None
        return Session(
            chat_id=values["chat_id"],
            owner_id=int(values["owner_id"]),
            conversation_id=values.get("conversation_id", ""),
            task_id=values.get("task_id", ""),
        )

    async def create(self, owner_id: int = 0, replacement: bool = False) -> Session:
        """Admit a conversation using a Redis-wide capacity limit."""
        session = Session(chat_id=str(uuid.uuid4()), owner_id=owner_id)
        admitted = await self.redis.eval(
            CREATE_SCRIPT,
            2,
            self.key("sessions"),
            self.key("session:" + session.chat_id),
            session.chat_id,
            owner_id,
            session.ttl,
            MAX_SESSIONS + int(replacement),
        )
        if not admitted:
            raise HTTPException(503, "助手会话数量已达上限，请稍后再试")
        return session

    async def discard(self, session: Session) -> None:
        """Remove a replaced session without touching persistent business feedback."""
        async with self.redis.pipeline(transaction=True) as pipe:
            pipe.delete(self.key("session:" + session.chat_id), self.key("history:" + session.chat_id))
            pipe.zrem(self.key("sessions"), session.chat_id)
            await pipe.execute()

    async def bind(self, session: Session, browser_key: str, auth_token: str = "") -> Session:
        """Bind an opaque tab capability to a server-owned conversation and token."""
        session.browser_key, session.auth_token = browser_key, auth_token
        await self.redis.set(
            self.key("browser:" + browser_key),
            json.dumps({"chat_id": session.chat_id, "auth_token": auth_token}),
            ex=ANONYMOUS_TTL,
        )
        await self.touch(session)
        return session

    async def open(self, tab_key: str, token: str) -> Session:
        """Restore only the identity explicitly supplied by the current tab."""
        if token:
            owner = await self.identity(token)
            active_key = self.key(f"user:{owner}:active")
            current = await self.redis.get(active_key)
            session = await self.load(current) if current else None
            if session is None:
                candidate = await self.create(owner)
                # Remove a stale pointer before NX, then account for simultaneous device logins.
                if current:
                    await self.redis.eval(
                        "if redis.call('GET',KEYS[1])==ARGV[1] then return redis.call('DEL',KEYS[1]) end return 0",
                        1,
                        active_key,
                        current,
                    )
                won = await self.redis.set(active_key, candidate.chat_id, nx=True, ex=ACCOUNT_TTL)
                if won:
                    session = candidate
                else:
                    current = await self.redis.get(active_key)
                    session = await self.load(current) if current else None
                    await self.discard(candidate)
                    if session is None:
                        raise HTTPException(409, "账户会话正在更新，请重试恢复")
            if session.owner_id != owner:
                raise HTTPException(403, "账户会话不匹配")
            # A fresh binding cannot inherit a previous user's token on a shared browser.
            binding_key = secrets.token_urlsafe(32)
            if tab_key:
                raw = await self.redis.get(self.key("browser:" + tab_key))
                if raw and json.loads(raw).get("auth_token") == token:
                    binding_key = tab_key
            return await self.bind(session, binding_key, token)
        if tab_key:
            binding = await self.redis.get(self.key("browser:" + tab_key))
            if binding:
                data = json.loads(binding)
                session = await self.load(data["chat_id"])
                if session and not session.owner_id and not data.get("auth_token"):
                    return await self.bind(session, tab_key)
        return await self.bind(await self.create(), secrets.token_urlsafe(32))

    async def resolve(self, tab_key: str, token: str, expected_chat_id: str) -> Session:
        """Require the tab capability, current token and exact conversation on every operation."""
        # A stored token never substitutes for an omitted or expired request token.
        owner = await self.identity(token) if token else 0
        raw = await self.redis.get(self.key("browser:" + tab_key)) if tab_key else None
        if not raw:
            raise HTTPException(401, "助手会话已过期，请重新连接")
        binding = json.loads(raw)
        session = await self.load(binding["chat_id"])
        if binding.get("auth_token", "") != token:
            raise HTTPException(403, "助手会话与当前标签页的登录凭证不匹配，请重新连接")
        if not session or session.chat_id != expected_chat_id:
            raise HTTPException(409, "助手会话已更新，请重新连接")
        if session.owner_id != owner:
            raise HTTPException(403, "助手会话与登录用户不匹配")
        if owner:
            active = await self.redis.get(self.key(f"user:{owner}:active"))
            if active != expected_chat_id:
                raise HTTPException(409, "账户会话已更新，请恢复聊天")
        return await self.bind(session, tab_key, token)

    async def touch(self, session: Session) -> None:
        """Refresh retention without overwriting another worker's conversation fields."""
        await self.redis.eval(
            """
            if redis.call('EXISTS',KEYS[1])==0 then return 0 end
            local t=redis.call('TIME'); local now=tonumber(t[1])
            redis.call('EXPIRE',KEYS[1],ARGV[1]); redis.call('EXPIRE',KEYS[2],ARGV[1])
            redis.call('ZADD',KEYS[3],now+tonumber(ARGV[1]),ARGV[2])
            if ARGV[3]~='0' then redis.call('EXPIRE',KEYS[4],ARGV[1]) end
            return 1
            """,
            4,
            self.key("session:" + session.chat_id),
            self.key("history:" + session.chat_id),
            self.key("sessions"),
            self.key(f"user:{session.owner_id}:active"),
            session.ttl,
            session.chat_id,
            session.owner_id,
        )

    async def reset(self, previous: Session) -> Session:
        """Switch every device to a fresh conversation; retain the account binding."""
        lease = await self.acquire(previous)
        try:
            await self.rate("reset:" + previous.browser_key, 5)
            if (
                previous.owner_id
                and await self.redis.get(self.key(f"user:{previous.owner_id}:active")) != previous.chat_id
            ):
                raise HTTPException(409, "账户会话已更新，请恢复聊天")
            current = await self.create(previous.owner_id, replacement=True)
            current.browser_key, current.auth_token = previous.browser_key, previous.auth_token
            async with self.redis.pipeline(transaction=True) as pipe:
                if current.owner_id:
                    pipe.set(self.key(f"user:{current.owner_id}:active"), current.chat_id, ex=current.ttl)
                pipe.set(
                    self.key("browser:" + current.browser_key),
                    json.dumps({"chat_id": current.chat_id, "auth_token": current.auth_token}),
                    ex=ANONYMOUS_TTL,
                )
                pipe.delete(self.key("session:" + previous.chat_id), self.key("history:" + previous.chat_id))
                pipe.zrem(self.key("sessions"), previous.chat_id)
                await pipe.execute()
            return current
        finally:
            await self.release(previous, lease)

    async def rate(self, subject: str, maximum: int) -> None:
        """Enforce one rolling limit across all workers and instances."""
        allowed = await self.redis.eval(RATE_SCRIPT, 1, self.key("rate:" + subject), maximum, str(uuid.uuid4()))
        if not allowed:
            raise HTTPException(429, "操作太频繁，请稍后再试")

    async def acquire(self, session: Session) -> str:
        """Lease a chat and a global stream slot atomically, with crash expiry."""
        lease = str(uuid.uuid4())
        result = await self.redis.eval(
            ACQUIRE_SCRIPT,
            4,
            self.key("lease:" + session.chat_id),
            self.streams_key,
            self.key("session:" + session.chat_id),
            self.key(f"user:{session.owner_id}:active"),
            lease,
            MAX_STREAMS,
            LEASE_SECONDS,
            session.owner_id,
            session.chat_id,
        )
        if result == 0:
            raise HTTPException(409, "这个对话正在另一窗口或设备生成回答，请稍后恢复聊天")
        if result == 1:
            raise HTTPException(503, "助手当前繁忙，请稍后再试")
        if result == 3:
            raise HTTPException(409, "聊天会话已更新，请恢复聊天")
        session.lease = lease
        return lease

    async def release(self, session: Session, lease: str) -> None:
        """A delayed worker can never release a newer worker's lease."""
        await self.redis.eval(RELEASE_SCRIPT, 2, self.key("lease:" + session.chat_id), self.streams_key, lease)

    async def busy(self, session: Session) -> bool:
        """Expose conversation progress without exposing its lease token."""
        return bool(await self.redis.exists(self.key("lease:" + session.chat_id)))

    async def update(self, session: Session) -> None:
        """Write Dify IDs only while this worker owns the generating lease."""
        await self.redis.eval(
            """
            if redis.call('GET',KEYS[1])~=ARGV[1] or redis.call('EXISTS',KEYS[2])==0 then return 0 end
            redis.call('HSET',KEYS[2],'conversation_id',ARGV[2],'task_id',ARGV[3]); return 1
            """,
            2,
            self.key("lease:" + session.chat_id),
            self.key("session:" + session.chat_id),
            session.lease,
            session.conversation_id,
            session.task_id,
        )

    async def clear_task(self, session: Session, task_id: str) -> None:
        """Clear only the task that was actually stopped or completed."""
        await self.redis.eval(
            "if redis.call('HGET',KEYS[1],'task_id')==ARGV[1] then redis.call('HSET',KEYS[1],'task_id','') end return 1",
            1,
            self.key("session:" + session.chat_id),
            task_id,
        )

    async def cancel(self, session: Session) -> None:
        """Let a stop request on any instance target the active generating lease."""
        lease = await self.redis.get(self.key("lease:" + session.chat_id))
        if lease:
            await self.redis.set(self.key("cancel:" + session.chat_id), lease, ex=LEASE_SECONDS)

    async def cancelled(self, session: Session) -> bool:
        """Ignore stale cancellation requests from older turns."""
        return await self.redis.get(self.key("cancel:" + session.chat_id)) == session.lease

    async def save_snapshot(self, record: Snapshot) -> None:
        """Persist bounded feedback metadata with a Redis-wide count and TTL cap."""
        if record.provider.lower() != self.channel:
            raise ValueError("Feedback provider does not match this chat channel")
        remaining = max(1, min(SNAPSHOT_TTL, int(record.created + SNAPSHOT_TTL - time.time())))
        await self.redis.eval(
            SNAPSHOT_SCRIPT,
            2,
            self.key("snapshots"),
            self.key("snapshot:" + record.message_id),
            record.message_id,
            json.dumps(asdict(record), ensure_ascii=False),
            remaining,
            MAX_SNAPSHOTS,
            self.key("snapshot:"),
        )

    async def snapshot(self, message_id: str) -> Snapshot | None:
        """Read feedback on any worker; IDs alone do not confer message ownership."""
        raw = await self.redis.get(self.key("snapshot:" + message_id))
        return Snapshot(**json.loads(raw)) if raw else None

    async def finish(self, session: Session, record: Snapshot) -> None:
        """Atomically save recent user/assistant messages and trusted feedback context."""
        if record.session_id != session.chat_id:
            raise ValueError("Feedback conversation does not match the generating session")
        await self.save_snapshot(record)
        user = {"id": str(uuid.uuid4()), "role": "user", "content": record.question, "mode": record.provider.lower()}
        assistant = {
            "id": record.message_id,
            "messageId": record.message_id,
            "role": "assistant",
            "content": record.answer,
            "mode": record.provider.lower(),
            "failed": bool(record.error_code),
            "finished": True,
            "normalizedQuestion": str(record.context.get("normalized_question", "")),
            "truncated": record.truncated,
        }
        # Check the lease and conversation inside Lua so an expired worker cannot append to a replaced chat.
        await self.redis.eval(
            """
            if redis.call('GET',KEYS[1])~=ARGV[1] or redis.call('EXISTS',KEYS[2])==0 then return 0 end
            redis.call('RPUSH',KEYS[3],ARGV[2],ARGV[3]); redis.call('LTRIM',KEYS[3],-40,-1)
            redis.call('EXPIRE',KEYS[3],ARGV[4]); return 1
            """,
            3,
            self.key("lease:" + session.chat_id),
            self.key("session:" + session.chat_id),
            self.key("history:" + session.chat_id),
            session.lease,
            json.dumps(user, ensure_ascii=False),
            json.dumps(assistant, ensure_ascii=False),
            session.ttl,
        )

    async def history(self, session: Session) -> list[dict[str, Any]]:
        """Restore forty recent messages; expired feedback remains visibly unavailable."""
        records = [json.loads(raw) for raw in await self.redis.lrange(self.key("history:" + session.chat_id), -40, -1)]
        assistants = [item for item in records if item["role"] == "assistant"]
        if assistants:
            snapshots = await self.redis.mget([self.key("snapshot:" + item["id"]) for item in assistants])
            for item, raw in zip(assistants, snapshots, strict=True):
                if raw:
                    item["feedback"] = json.loads(raw).get("feedback", {})
                else:
                    item.pop("messageId", None)
        return records

    async def feedback_lock(self, record: Snapshot) -> str:
        """Serialize feedback votes across instances, including Dify synchronization."""
        token = str(uuid.uuid4())
        if not await self.redis.set(self.key("feedback-lock:" + record.message_id), token, nx=True, ex=40):
            raise HTTPException(409, "该评价正在保存，请稍后重试")
        return token

    async def feedback_unlock(self, record: Snapshot, token: str) -> None:
        """Release only this feedback operation's lease."""
        await self.redis.eval(
            "if redis.call('GET',KEYS[1])==ARGV[1] then return redis.call('DEL',KEYS[1]) end return 0",
            1,
            self.key("feedback-lock:" + record.message_id),
            token,
        )
