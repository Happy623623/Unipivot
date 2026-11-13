import type { Me } from "@/types/api";

// 동의 문구(components/onboarding/ConsentStep.tsx)를 바꾸면 이 버전을 올리고 ConsentStep의 바뀐 점(CONSENT_CHANGES)을 고친다.
// 버전은 동의할 때 profiles.consent_version에 남는다. 이미 동의한 사람은 버전이 다르면 다음에 앱을 열 때 다시 묻는다(F-02)
export const CONSENT_VERSION = "2026-11-24";

// 이미 동의했는데 지금 문구보다 옛 버전이면 다시 묻는다. 버전은 날짜(YYYY-MM-DD)라 글자 순서가 날짜 순서다 —
// 더 새 버전에 동의한 사람(배포를 되돌렸거나 오래 열어 둔 탭)에게 옛 문구를 다시 묻지 않는다.
// 옛 api는 consent_version을 주지 않는다(undefined) — 그때는 묻지 않는다. 다시 동의해도 버전이 보이지 않아
// 같은 화면을 되풀이하지 않게(api를 늦게 배포해도 괜찮다)
export function needsConsentRenewal(me: Pick<Me, "consented" | "consent_version">): boolean {
  return me.consented && typeof me.consent_version === "string" && me.consent_version < CONSENT_VERSION;
}
