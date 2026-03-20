/** 以 full_name 是否 cc: 前缀区分 CodeCommit / GitHub */
export function repoSource(fullName: string): "cc" | "gh" {
  return fullName.trim().toLowerCase().startsWith("cc:") ? "cc" : "gh";
}

export function RepoSourceBadge({ fullName }: { fullName: string }) {
  const src = repoSource(fullName);
  return (
    <span
      className={`pill repo-source-badge ${src === "cc" ? "warn" : "ok"}`}
      title={src === "cc" ? "AWS CodeCommit（.env 配 AWS 密钥）" : "GitHub（可选 GITHUB_TOKEN）"}
    >
      {src === "cc" ? "CodeCommit" : "GitHub"}
    </span>
  );
}
