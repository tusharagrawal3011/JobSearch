"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { api } from "../lib/api";

const LINKS = [
  { href: "/tracker", label: "My Applications", key: null },
  { href: "/diffs", label: "Diff Approval", key: "resume_diffs" },
  { href: "/apply", label: "Apply Queue", key: "apply_queue" },
  { href: "/screening", label: "Screening Q&A", key: "unanswered_screening" },
  { href: "/outreach", label: "Outreach", key: "outreach_drafts" },
  { href: "/add-company", label: "Add Company", key: null },
  { href: "/digest", label: "Daily Digest", key: null },
];

export default function Nav() {
  const path = usePathname();
  const [counts, setCounts] = useState({});

  useEffect(() => {
    api.get("/api/digest").then((d) => setCounts(d.pending || {})).catch(() => {});
  }, [path]);

  return (
    <aside className="sidebar">
      <div className="brand">Job Application Agent
        <small>{process.env.NEXT_PUBLIC_OWNER_NAME || "your local job-search assistant"}</small>
      </div>
      <nav className="nav">
        {LINKS.map((l) => (
          <Link key={l.href} href={l.href} className={path === l.href ? "active" : ""}>
            <span>{l.label}</span>
            {l.key && counts[l.key] > 0 ? <span className="badge">{counts[l.key]}</span> : null}
          </Link>
        ))}
      </nav>
    </aside>
  );
}
