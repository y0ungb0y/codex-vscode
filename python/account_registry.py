"""Dynamic account metadata with stable numeric slots and reversible removal."""
import datetime
import json
import pathlib
import re
import uuid

from providers import commit, read_bytes


def account_id(value):
    return isinstance(value, str) and re.fullmatch(r'[1-9][0-9]{0,5}', value) is not None


def email_address(value):
    return (isinstance(value, str) and len(value) <= 254
            and not any(ord(c) < 32 or ord(c) == 127 for c in value)
            and re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', value) is not None)


class AccountRegistry:
    def __init__(self, root, seeds):
        self.root = pathlib.Path(root)
        self.path = self.root / 'accounts.json'
        self.seeds = seeds

    def document(self):
        try:
            if self.path.is_symlink():
                raise ValueError()
            raw = read_bytes(self.path)
            doc = json.loads(raw.decode('utf-8-sig')) if raw is not None else {'version': 1, 'emails': self.seeds}
            emails = doc['emails']
            if (not isinstance(emails, dict) or len(emails) > 250
                    or any(not account_id(n) or not email_address(e) for n, e in emails.items())
                    or len({e.lower() for e in emails.values()}) != len(emails)):
                raise ValueError()
            minimum = max([int(n) for n in emails] + [0]) + 1
            if raw is None and self.root.exists():
                minimum = max([minimum] + [int(p.name) + 1 for p in self.root.iterdir() if account_id(p.name)])
            next_id = doc.get('nextId', minimum)
            if type(next_id) is not int or next_id < minimum or next_id > 1000000:
                raise ValueError()
            return raw, {'version': 1, 'emails': dict(sorted(emails.items(), key=lambda item: int(item[0]))), 'nextId': next_id}
        except (ValueError, KeyError, TypeError, UnicodeError):
            raise ValueError('账号列表格式无效；未修改账号或凭据，请检查 accounts.json 与初始邮箱设置。')

    def emails(self):
        return self.document()[1]['emails']

    @staticmethod
    def encode(value):
        return json.dumps(value, ensure_ascii=False, indent=2).encode('utf-8')

    def add(self, email):
        email = email.strip() if isinstance(email, str) else email
        if not email_address(email):
            raise ValueError('请输入有效的账号邮箱。')
        raw, doc = self.document()
        if any(e.lower() == email.lower() for e in doc['emails'].values()):
            raise ValueError('此邮箱已在账号列表中，请使用现有账号的授权按钮。')
        if len(doc['emails']) >= 250:
            raise ValueError('账号数量已达到 250 个，请先移除不再使用的账号。')
        number = doc['nextId']
        while number <= 999999 and (self.root / str(number)).exists():
            number += 1
        if number > 999999:
            raise ValueError('账号编号已用完。')
        doc['emails'][str(number)] = email
        doc['nextId'] = number + 1
        commit({self.path: self.encode(doc)}, {self.path: raw})
        return str(number)

    def remove(self, number, default_auth, current_email, expected_email=None):
        if not account_id(number):
            raise ValueError('账号编号无效。')
        raw, doc = self.document()
        if number not in doc['emails']:
            raise ValueError('账号已不存在，请刷新列表。')
        email = doc['emails'][number]
        if expected_email is not None and expected_email.lower() != email.lower():
            raise ValueError('账号列表已变化，请刷新后重试。')
        target = self.root / number / 'auth.json'
        default_auth = pathlib.Path(default_auth)
        if ((current_email or '').lower() == email.lower()
                or default_auth.resolve() == target.resolve()):
            raise ValueError('请先切换到其他账号，再删除当前使用的账号。')
        if target.parent.is_symlink() or target.is_symlink():
            raise ValueError('账号凭据目录包含符号链接，未删除；请先检查目录。')
        name = datetime.datetime.now().strftime('%Y%m%d-%H%M%S-') + uuid.uuid4().hex[:8] + '-' + number
        backup = self.root / 'account-delete-backups' / name
        del doc['emails'][number]
        credential = read_bytes(target)
        changes = {backup / 'accounts.json': raw or self.encode(self.document()[1]), self.path: self.encode(doc)}
        if credential is not None:
            changes[backup / 'auth.json'] = credential
            changes[target] = None
        # Commit validates all expected bytes before any removal and rolls back write failures.
        commit(changes, {self.path: raw, target: credential})
        return str(backup)
