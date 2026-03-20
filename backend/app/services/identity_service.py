from __future__ import annotations

from collections import Counter
from typing import Any, Iterable

from sqlalchemy import false, func, or_, select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import CommitRecord, Contributor, ContributorAlias


def normalize_email(value: str | None) -> str | None:
    if not value:
        return None
    s = value.strip().lower()
    return s or None


class AliasMaps:
    __slots__ = ("by_email", "by_login")

    def __init__(self, by_email: dict[str, Contributor], by_login: dict[str, Contributor]):
        self.by_email = by_email
        self.by_login = by_login


def load_alias_maps(db: Session) -> AliasMaps:
    contributors = {c.id: c for c in db.execute(select(Contributor)).scalars().all()}
    by_email: dict[str, Contributor] = {}
    by_login: dict[str, Contributor] = {}
    for a in db.execute(select(ContributorAlias)).scalars().all():
        c = contributors.get(a.contributor_id)
        if not c:
            continue
        if a.kind == "email":
            by_email[a.value_normalized] = c
        elif a.kind == "login":
            by_login[a.value_normalized] = c
    return AliasMaps(by_email, by_login)


def resolve_employee_key_parts(
    author_login: str | None,
    author_email: str | None,
    maps: AliasMaps,
) -> tuple[str, Contributor | None]:
    """邮箱优先匹配档案（适合用邮箱提交、与 GitHub 登录并存时）。"""
    email = normalize_email(author_email)
    login = (author_login or "").strip().lower() or None
    if email and email in maps.by_email:
        c = maps.by_email[email]
        return f"contrib:{c.id}", c
    if login and login in maps.by_login:
        c = maps.by_login[login]
        return f"contrib:{c.id}", c
    if login:
        return login, None
    if email:
        return f"email:{email}", None
    return "_unknown", None


def resolve_employee_key(commit: CommitRecord, maps: AliasMaps) -> tuple[str, Contributor | None]:
    return resolve_employee_key_parts(commit.author_login, commit.author_email, maps)


def sort_employee_keys(keys: Iterable[str]) -> list[str]:
    def sk(x: str) -> tuple:
        if x.startswith("contrib:"):
            return (0, int(x.split(":")[1]))
        if x == "_unknown":
            return (4, x)
        if x.startswith("email:"):
            return (2, x)
        return (1, x)

    return sorted(keys, key=sk)


def configured_member_key(login: str, maps: AliasMaps) -> str:
    ml = login.strip().lower()
    if ml in maps.by_login:
        return f"contrib:{maps.by_login[ml].id}"
    return ml


def commit_filter_for_employee_key(key: str, db: Session):
    """返回 SQLAlchemy where 条件（用于 commits / habits 查询）。"""
    kl = key.strip()
    if kl.lower().startswith("contrib:"):
        cid = int(kl.split(":", 1)[1])
        aliases = db.execute(
            select(ContributorAlias).where(ContributorAlias.contributor_id == cid)
        ).scalars().all()
        emails = [a.value_normalized for a in aliases if a.kind == "email"]
        logins = [a.value_normalized for a in aliases if a.kind == "login"]
        parts = []
        if logins:
            parts.append(CommitRecord.author_login.in_(logins))
        if emails:
            parts.append(func.lower(CommitRecord.author_email).in_(emails))
        if not parts:
            return false()
        return or_(*parts) if len(parts) > 1 else parts[0]
    if kl.lower().startswith("email:"):
        em = kl.split(":", 1)[1].strip().lower()
        return (CommitRecord.author_email.isnot(None)) & (func.lower(CommitRecord.author_email) == em)
    if kl == "_unknown":
        return CommitRecord.author_login.is_(None) & (
            CommitRecord.author_email.is_(None) | (CommitRecord.author_email == "")
        )
    return CommitRecord.author_login == kl.lower()


def suggested_employee_keys(db: Session) -> list[str]:
    """用于前端下拉：去重后的报表主键（含档案、邮箱桶、GitHub 登录）。"""
    maps = load_alias_maps(db)
    keys: set[str] = set()
    pairs = db.execute(
        select(CommitRecord.author_login, CommitRecord.author_email).distinct()
    ).all()
    for login, email in pairs:
        k, _ = resolve_employee_key_parts(login, email, maps)
        keys.add(k)
    for m in settings.member_logins:
        keys.add(configured_member_key(m, maps))
    for c in db.execute(select(Contributor)).scalars().all():
        keys.add(f"contrib:{c.id}")
    return sort_employee_keys(keys)


def display_label_for_employee_key(key: str, contributors_by_id: dict[int, Contributor]) -> str:
    """下拉展示用：contrib 用昵称；email: 用邮箱；其余保持原样。"""
    k = key.strip()
    kl = k.lower()
    if kl.startswith("contrib:"):
        try:
            cid = int(k.split(":", 1)[1])
        except ValueError:
            return k
        c = contributors_by_id.get(cid)
        nick = (c.nickname or "").strip() if c else ""
        return nick or f"成员档案 #{cid}"
    if kl == "_unknown":
        return "未绑定登录/邮箱"
    if kl.startswith("email:"):
        rest = k.split(":", 1)[1].strip()
        return rest or k
    return k


def suggested_employee_key_options(db: Session) -> list[dict[str, str]]:
    """供前端下拉：key 为实际报表主键，label 为人类可读名称。"""
    keys = suggested_employee_keys(db)
    by_id = {c.id: c for c in db.execute(select(Contributor)).scalars().all()}
    raw = [display_label_for_employee_key(k, by_id) for k in keys]
    cnt = Counter(raw)
    out: list[dict[str, str]] = []
    for k, lab in zip(keys, raw):
        label = lab
        if cnt[lab] > 1 and k.lower().startswith("contrib:"):
            try:
                cid = int(k.split(":", 1)[1])
            except ValueError:
                pass
            else:
                label = f"{lab} · #{cid}"
        out.append({"key": k, "label": label})
    return out


def provision_contributor_if_missing(
    db: Session,
    *,
    author_login: str | None,
    author_email: str | None,
    author_name: str | None,
) -> bool:
    """
    若邮箱或登录尚未绑定任何成员档案，则新建 Contributor 并写入别名。
    当登录已被他人占用而邮箱为新时，仅添加邮箱别名（避免伪登录撞车）。
    """
    email = normalize_email(author_email)
    login = (author_login or "").strip().lower() or None
    if not email and not login:
        return False
    maps = load_alias_maps(db)
    if email and email in maps.by_email:
        return False
    if not email and login and login in maps.by_login:
        return False

    nick = (author_name or "").strip()
    if not nick:
        nick = email.split("@", 1)[0] if email else (login or "成员")
    nick = nick[:128] or "成员"

    c = Contributor(nickname=nick, notes="同步自动创建")
    db.add(c)
    db.flush()
    if email:
        db.add(ContributorAlias(contributor_id=c.id, kind="email", value_normalized=email))
    if login and login not in maps.by_login:
        db.add(ContributorAlias(contributor_id=c.id, kind="login", value_normalized=login))
    return True


def provision_contributors_from_normalized(db: Session, normalized_commits: list[dict[str, Any]]) -> int:
    from app.config import settings

    if not settings.auto_provision_contributors or not normalized_commits:
        return 0
    seen: set[tuple[str | None, str | None]] = set()
    created = 0
    for norm in normalized_commits:
        login = (norm.get("author_login") or "").strip().lower() or None
        email = normalize_email(norm.get("author_email"))
        name = (norm.get("author_name") or "").strip() or None
        key = (email, login)
        if key in seen:
            continue
        seen.add(key)
        if provision_contributor_if_missing(
            db, author_login=login, author_email=email, author_name=name
        ):
            created += 1
    return created
