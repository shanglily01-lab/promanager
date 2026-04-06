import { useEffect, useState } from "react";
import type { ContributorOut } from "../api";
import { deleteJson, getJson, postJson, putJson } from "../api";

type Props = { onError: (msg: string | null) => void; team: string };

function splitLines(s: string): string[] {
  return s
    .split(/[\n,;]+/)
    .map((x) => x.trim())
    .filter(Boolean);
}

export function ContributorsTab({ onError, team }: Props) {
  const [contributors, setContributors] = useState<ContributorOut[]>([]);
  const [showForm, setShowForm] = useState(false);
  const [contribNick, setContribNick] = useState("");
  const [contribNotes, setContribNotes] = useState("");
  const [contribEmails, setContribEmails] = useState("");
  const [contribLogins, setContribLogins] = useState("");
  const [editingContribId, setEditingContribId] = useState<number | null>(null);

  useEffect(() => {
    getJson<ContributorOut[]>(`/api/contributors?team=${encodeURIComponent(team)}`)
      .then(setContributors)
      .catch(() => setContributors([]));
  }, [team]);

  const resetContribForm = () => {
    setContribNick("");
    setContribNotes("");
    setContribEmails("");
    setContribLogins("");
    setEditingContribId(null);
    setShowForm(false);
  };

  const startEditContributor = (c: ContributorOut) => {
    setShowForm(true);
    setEditingContribId(c.id);
    setContribNick(c.nickname);
    setContribNotes(c.notes || "");
    setContribEmails(c.aliases.filter((a) => a.kind === "email").map((a) => a.value_normalized).join("\n"));
    setContribLogins(c.aliases.filter((a) => a.kind === "login").map((a) => a.value_normalized).join("\n"));
  };

  const saveContributor = async () => {
    onError(null);
    if (!contribNick.trim()) {
      onError("请填写昵称");
      return;
    }
    const body = {
      nickname: contribNick.trim(),
      notes: contribNotes.trim(),
      emails: splitLines(contribEmails),
      github_logins: splitLines(contribLogins),
      team,
    };
    try {
      if (editingContribId != null) {
        await putJson<ContributorOut>(`/api/contributors/${editingContribId}`, body);
      } else {
        await postJson<ContributorOut>("/api/contributors", body);
      }
      const list = await getJson<ContributorOut[]>(`/api/contributors?team=${encodeURIComponent(team)}`);
      setContributors(list);
      resetContribForm();
    } catch (e) {
      onError(String(e));
    }
  };

  const removeContributor = async (id: number) => {
    if (!confirm("确定删除该成员档案？")) return;
    onError(null);
    try {
      await deleteJson(`/api/contributors/${id}`);
      setContributors(await getJson<ContributorOut[]>(`/api/contributors?team=${encodeURIComponent(team)}`));
      if (editingContribId === id) resetContribForm();
    } catch (e) {
      onError(String(e));
    }
  };

  return (
    <div>
      <div className="page-header">
        <h2 className="page-title">成员档案</h2>
      </div>
      <div className="row" style={{ marginBottom: "0.75rem" }}>
        <button
          type="button"
          className={showForm && editingContribId == null ? "ghost" : "primary"}
          onClick={() => { resetContribForm(); setShowForm((v) => !v); }}
        >
          {showForm && editingContribId == null ? "收起" : "+ 新增成员档案"}
        </button>
      </div>

      {showForm && (
        <>
          <div className="row row--stretch">
            <label className="field-grow">
              昵称（展示名）
              <input value={contribNick} onChange={(e) => setContribNick(e.target.value)} />
            </label>
          </div>
          <label>
            备注（可选）
            <input value={contribNotes} onChange={(e) => setContribNotes(e.target.value)} />
          </label>
          <label>
            邮箱（每行一个，或逗号分隔）
            <textarea
              value={contribEmails}
              onChange={(e) => setContribEmails(e.target.value)}
              placeholder={"zhang@company.com\nzhang@gmail.com"}
              spellCheck={false}
              className="textarea-short"
            />
          </label>
          <label>
            GitHub 登录（每行一个，小写）
            <textarea
              value={contribLogins}
              onChange={(e) => setContribLogins(e.target.value)}
              placeholder="zhangsan"
              spellCheck={false}
              className="textarea-compact"
            />
          </label>
          <div className="row">
            <button type="button" className="primary" onClick={saveContributor}>
              {editingContribId != null ? "保存修改" : "新增成员"}
            </button>
            <button type="button" className="ghost" onClick={resetContribForm}>
              取消
            </button>
          </div>
        </>
      )}

      <h2 className="subsection-title">已有档案</h2>
      <div className="employee-grid">
        {contributors.map((c) => (
          <div key={c.id} className="employee-card">
            <h3 className="contrib-card-title">
              {c.nickname} <code className="contrib-id">contrib:{c.id}</code>
            </h3>
            {c.notes && <div className="contrib-notes">{c.notes}</div>}
            <ul className="commit-list">
              {c.aliases.map((a) => (
                <li key={a.id}>
                  {a.kind === "email" ? "邮箱" : "GitHub"} · {a.value_normalized}
                </li>
              ))}
            </ul>
            <div className="row row--card-actions">
              <button type="button" className="ghost" onClick={() => startEditContributor(c)}>
                编辑
              </button>
              <button type="button" className="ghost" onClick={() => removeContributor(c.id)}>
                删除
              </button>
            </div>
          </div>
        ))}
      </div>
      {contributors.length === 0 && <p className="card-hint" style={{ padding: "0 1rem" }}>暂无档案，可在上方新增。</p>}
    </div>
  );
}
