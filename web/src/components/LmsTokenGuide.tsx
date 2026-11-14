// LearningX 액세스 토큰 발급 안내 그림 세 장(PRD F-50). 캡처 대신 LearningX 화면을 단순하게 그렸다 — 이름·학번
// 같은 개인정보가 나올 일이 없다. 그림 속 글자(계정·설정·승인된 통합·새 액세스 토큰·목적·만료일·토큰 생성)와 색은
// 11/13에 LearningX 설정 화면에서 그대로 옮겼다. 실제 캡처로 바꾸려면 이 파일만 바꾼다
const LX_BLUE = "#004483"; // LearningX 왼쪽 메뉴와 주 버튼 색
const LX_TEXT = "#2d3b45";
const MARK = "#f59e0b"; // 누를 곳. 앱의 파랑과 헷갈리지 않게 주황으로 둘렀다
const LINE = "#d0d5dd";

// 1. 왼쪽 맨 위 '계정' → 펼쳐진 목록의 '설정'
function AccountArt() {
  return (
    <svg viewBox="0 0 160 120" className="block h-auto w-full" aria-hidden="true">
      <rect width={160} height={120} fill="#f7f8fa" />
      <rect width={34} height={120} fill={LX_BLUE} />
      <circle cx={17} cy={15} r={8} fill="#fff" opacity={0.95} />
      <text x={17} y={35} textAnchor="middle" fontSize={8.5} fill="#fff">
        계정
      </text>
      <rect x={4} y={9} width={26} height={30} rx={4} fill="none" stroke={MARK} strokeWidth={2} />
      {[50, 68, 86, 104].map((y) => (
        <rect key={y} x={11} y={y} width={12} height={9} rx={2} fill="#fff" opacity={0.4} />
      ))}
      <rect x={34} width={78} height={120} fill="#fff" stroke={LINE} strokeWidth={0.5} />
      <rect x={42} y={10} width={52} height={7} rx={3} fill="#e5e7eb" />
      <text x={44} y={40} fontSize={11} fill={LX_TEXT}>
        알림
      </text>
      <text x={44} y={60} fontSize={11} fill={LX_TEXT}>
        파일
      </text>
      <rect x={39} y={68} width={66} height={19} rx={4} fill="#fff7e6" stroke={MARK} strokeWidth={2} />
      <text x={44} y={81} fontSize={11} fontWeight={700} fill={LX_TEXT}>
        설정
      </text>
      <text x={44} y={104} fontSize={11} fill={LX_TEXT}>
        전체 공지
      </text>
      {[24, 40, 56, 72].map((y) => (
        <rect key={y} x={118} y={y} width={34} height={5} rx={2} fill="#e5e7eb" />
      ))}
    </svg>
  );
}

// 2. 설정 화면 '승인된 통합' 아래 '+ 새 액세스 토큰'
function NewTokenArt() {
  return (
    <svg viewBox="0 0 160 120" className="block h-auto w-full" aria-hidden="true">
      <rect width={160} height={120} fill="#fff" />
      <rect width={12} height={120} fill={LX_BLUE} />
      <text x={22} y={25} fontSize={12} fontWeight={700} fill={LX_TEXT}>
        승인된 통합
      </text>
      <rect x={22} y={34} width={128} height={14} fill="#f2f4f7" />
      <text x={26} y={44} fontSize={8} fill="#667085">
        앱
      </text>
      <text x={62} y={44} fontSize={8} fill="#667085">
        목적
      </text>
      <text x={110} y={44} fontSize={8} fill="#667085">
        날짜
      </text>
      <rect x={26} y={55} width={118} height={5} rx={2} fill="#e5e7eb" />
      <rect x={26} y={67} width={96} height={5} rx={2} fill="#e5e7eb" />
      <rect x={22} y={84} width={98} height={22} rx={3} fill={LX_BLUE} />
      <text x={71} y={99} textAnchor="middle" fontSize={10.5} fontWeight={700} fill="#fff">
        + 새 액세스 토큰
      </text>
      <rect x={18} y={80} width={106} height={30} rx={6} fill="none" stroke={MARK} strokeWidth={2} />
    </svg>
  );
}

// 3. '새 액세스 토큰' 창 — 목적·만료일을 넣고 '토큰 생성'
function CreateArt() {
  return (
    <svg viewBox="0 0 160 120" className="block h-auto w-full" aria-hidden="true">
      <rect width={160} height={120} fill="#dfe3ea" />
      <rect x={10} y={8} width={140} height={104} rx={4} fill="#fff" stroke={LINE} />
      <text x={18} y={24} fontSize={10.5} fontWeight={700} fill={LX_TEXT}>
        새 액세스 토큰
      </text>
      <line x1={10} y1={31} x2={150} y2={31} stroke={LINE} />
      <text x={18} y={49} fontSize={9} fill={LX_TEXT}>
        목적
      </text>
      <rect x={54} y={39} width={88} height={15} rx={2} fill="#fff" stroke={LINE} />
      <text x={58} y={50} fontSize={9} fill={LX_TEXT}>
        UNIPIVOT
      </text>
      <text x={18} y={71} fontSize={9} fill={LX_TEXT}>
        만료일
      </text>
      <rect x={54} y={61} width={88} height={15} rx={2} fill="#fff" stroke={LINE} />
      <text x={58} y={72} fontSize={8.5} fill="#98a2b3">
        학기 마지막 날
      </text>
      <rect x={56} y={88} width={30} height={16} rx={3} fill="#f2f4f7" stroke={LINE} />
      <text x={71} y={99.5} textAnchor="middle" fontSize={9} fill={LX_TEXT}>
        취소
      </text>
      <rect x={90} y={88} width={52} height={16} rx={3} fill={LX_BLUE} />
      <text x={116} y={99.5} textAnchor="middle" fontSize={9} fontWeight={700} fill="#fff">
        토큰 생성
      </text>
      <rect x={86} y={84} width={60} height={24} rx={5} fill="none" stroke={MARK} strokeWidth={2} />
    </svg>
  );
}

export const TOKEN_GUIDE_STEPS = [
  { key: "account", art: <AccountArt />, text: "LearningX 왼쪽 맨 위 '계정'을 누르고 '설정'으로 가요" },
  { key: "new-token", art: <NewTokenArt />, text: "'승인된 통합' 아래 '+ 새 액세스 토큰'을 눌러요" },
  {
    key: "create",
    art: <CreateArt />,
    text: "목적(UNIPIVOT)과 만료일(학기 마지막 날)을 넣고 '토큰 생성'을 눌러 나온 토큰을 복사해요",
  },
] as const;

// 좁은 화면에서는 그림 옆에 설명을, 넓은 화면(모달 520px)에서는 그림 셋을 나란히 두고 아래에 설명을 둔다
export default function LmsTokenGuide() {
  return (
    <ol className="mt-4 grid gap-3 sm:grid-cols-3 sm:gap-2" aria-label="LearningX 액세스 토큰 발급 순서">
      {TOKEN_GUIDE_STEPS.map((step, index) => (
        <li key={step.key} className="flex items-center gap-3 sm:flex-col sm:items-stretch sm:gap-2">
          <div className="w-28 shrink-0 overflow-hidden rounded-[10px] border border-[#e5e7eb] sm:w-auto">{step.art}</div>
          <p className="text-[12px] leading-5 text-[#344054]">
            <b className="mr-1 text-[#4f6ef7]">{index + 1}</b>
            {step.text}
          </p>
        </li>
      ))}
    </ol>
  );
}
