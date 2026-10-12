import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // next dev가 AI 코딩 도구를 알아채면 web/AGENTS.md를 만든다. 규칙은 web/CLAUDE.md 하나로 두고 만들지 않게 한다
  agentRules: false,
};

export default nextConfig;
