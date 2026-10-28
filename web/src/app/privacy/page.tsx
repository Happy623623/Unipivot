import type { Metadata } from "next";
import Link from "next/link";
import type { ReactNode } from "react";

// 개인정보 처리방침(시범 운영판). 로그인 없이 열려야 해서 (app)·(auth) 묶음 밖에 둔다 — (app)은 들어오자마자
// 내 정보를 불러 로그인으로 보낸다. 정적 페이지라 빌드 때 HTML로 만들어진다(Google 인증 플랫폼 게시에 쓰는 주소).
// 방침 버전은 동의 버전(CONSENT_VERSION)과 따로 둔다. 문구를 바꾸면 시행일·버전을 올리고, 지난 버전은 맨 아래에 남긴다
const EFFECTIVE = "2026년 10월 28일";
const VERSION = "시범 운영판 v0.1";
const OFFICER = { name: "최연우", role: "UNIPIVOT 팀장", email: "yunwoo8299@gmail.com" };

export const metadata: Metadata = {
  title: "개인정보 처리방침 · UNIPIVOT",
  description: "UNIPIVOT이 처리하는 개인정보와 그 목적, 보유 기간, 이용자의 권리",
};

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="mt-9">
      <h2 className="text-[17px] font-semibold leading-[1.45]">{title}</h2>
      <div className="mt-3 flex flex-col gap-3 text-[14px] leading-7 text-[#344054]">{children}</div>
    </section>
  );
}

function List({ children }: { children: ReactNode }) {
  return <ul className="list-disc pl-5 marker:text-[#a0a4ab] [&>li]:mt-1">{children}</ul>;
}

function Table({ caption, head, rows }: { caption: string; head: string[]; rows: ReactNode[][] }) {
  return (
    // 좁은 화면에서는 표만 옆으로 밀고 페이지는 밀리지 않게 한다. 키보드로도 밀 수 있게 초점을 받는다
    <div
      role="region"
      aria-label={caption}
      tabIndex={0}
      className="overflow-x-auto rounded-[2px] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#4f6ef7]"
    >
      <table className="w-full min-w-[560px] border-collapse text-left text-[13px] leading-6">
        <caption className="sr-only">{caption}</caption>
        <thead>
          <tr>
            {head.map((cell) => (
              <th key={cell} scope="col" className="border border-[#e5e7eb] bg-[#f7f8fa] px-3 py-2 font-semibold text-[#181a20]">
                {cell}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => (
            <tr key={index}>
              {row.map((cell, column) =>
                column === 0 ? (
                  <th key={column} scope="row" className="border border-[#e5e7eb] px-3 py-2 align-top font-semibold text-[#181a20]">
                    {cell}
                  </th>
                ) : (
                  <td key={column} className="border border-[#e5e7eb] px-3 py-2 align-top">
                    {cell}
                  </td>
                ),
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// 바깥 사이트는 새 탭으로 연다. 화면 읽기 프로그램에도 새 탭이라고 알린다
function Out({ href, children }: { href: string; children: ReactNode }) {
  return (
    <a href={href} target="_blank" rel="noopener noreferrer" className="font-semibold text-[#4f6ef7] underline-offset-2 hover:underline">
      {children}
      <span className="sr-only">(새 탭)</span>
    </a>
  );
}

export default function PrivacyPage() {
  return (
    <main className="min-h-dvh bg-[#f7f8fa] px-4 py-12 text-[#181a20] max-[760px]:py-6">
      <article className="mx-auto w-full max-w-[760px] rounded-[18px] border border-[#e5e7eb] bg-white p-8 max-[760px]:p-5">
        <Link href="/" className="text-[24px] font-bold text-[#4f6ef7]">
          UNIPIVOT
        </Link>
        <h1 className="mt-4 text-[24px] font-bold leading-[1.4]">개인정보 처리방침</h1>
        <p className="mt-2 text-[13px] text-[#667085]">
          시행일: {EFFECTIVE} ({VERSION})
        </p>
        <p className="mt-5 text-[14px] leading-7 text-[#344054]">
          UNIPIVOT(이하 &quot;서비스&quot;)은 한양대학교 ERICA SW창업캡스톤디자인 과제로 시범 운영 중인 대학생용 공고 자격 판정·준비
          도우미입니다. 서비스는 「개인정보 보호법」에 따라 이용자의 개인정보를 아래와 같이 처리합니다.
        </p>

        <Section title="1. 처리하는 개인정보 항목과 목적">
          <Table
            caption="처리하는 개인정보 항목과 목적"
            head={["구분", "항목", "목적"]}
            rows={[
              ["로그인", "Google 계정 이메일, 이름, 프로필 사진 주소, 계정 식별 번호, 로그인 시각", "회원 식별, 로그인"],
              ["기본 프로필", "학교, 학과, 학년, 학적 상태, 학위과정", "공고 자격 판정"],
              ["성적·이수", "전체·직전 학기 평점과 만점 기준, 전체·직전 학기 이수 학점, 이수 학기 수", "공고 자격 판정"],
              ["나이·병역·지역", "생년월일, 병역 복무 개월 수, 거주 시·도와 시·군·구", "공고 자격 판정"],
              [
                <>
                  소득·수급
                  <br />
                  (별도 동의 시에만)
                </>,
                "학자금 지원구간, 기준 중위소득 대비 비율, 본인 연 소득 금액, 기초생활수급·차상위 여부",
                "소득 기준이 있는 장학금·정책 판정",
              ],
              ["기타 프로필", "취업 상태, 유학생 여부", "청년정책 등 자격 판정"],
              ["동의 기록", "이용약관·개인정보·소득정보 동의 시각과 동의 버전", "동의 확인"],
              [
                "이용 중 생기는 기록",
                "공고별 판정 결과, 관심·숨김 표시, 준비 일정과 플래너 할 일, 강의계획서에서 뽑은 일정, 강의자료 요약, 알림함 기록, 알림·자동 등록 설정",
                "서비스 제공",
              ],
              [
                "LMS 연동(선택)",
                "LearningX 개인 액세스 토큰과 사용자 번호, 과목·과제(제출 여부 포함)·공지·주차 자료 목록, 과목 공지 첨부 파일",
                "과제 마감·공지 알림, 캘린더 등록, 문서함",
              ],
              ["업로드 파일(선택)", "포스터 사진·PDF, 강의계획서·강의자료 PDF", "공고 요건 추출, 시험·발표·과제 일정 추출, 강의자료 요약"],
              [
                "Google 캘린더(선택)",
                "캘린더 접근 권한(토큰), 서비스가 등록한 일정의 기록",
                "공고 마감일·강의계획서 일정·LMS 과제 마감을 캘린더에 등록·수정·삭제",
              ],
              ["알림(선택)", "브라우저 웹 푸시 구독 정보(브라우저 정보 포함)", "마감·새 공고·새 과제 알림"],
              [
                "처리 기록",
                "AI 처리 단계, 소요 시간, 사용량·비용, 오류 내용과 그때의 처리 결과",
                "오류 확인, 성능·비용 측정",
              ],
              [
                "이용 이벤트",
                "앱을 연 날, 공고 조회, 프로필 입력 안내를 보고 입력했는지, LMS 연결 안내를 열고 연결했는지",
                "서비스 개선",
              ],
              ["접속 기록", "서버 접속 기록과 로그인 기록(IP 주소, 브라우저 정보, 시각)", "오류 확인, 보안"],
            ]}
          />
          <List>
            <li>프로필은 이용자가 직접 입력합니다. 판정에 필요한 항목을 입력하지 않은 공고는 &quot;정보 필요&quot;로 표시합니다.</li>
            <li>
              휴대폰으로 찍은 포스터 사진에는 촬영 위치·시각 같은 정보가 들어 있을 수 있고, 서비스는 사진 파일을 그대로 저장하고 Gemini로
              보냅니다. 원하지 않으면 화면 캡처나 PDF로 올려 주세요.
            </li>
            <li>대학생 대상 서비스라 만 14세 미만 아동을 대상으로 하지 않습니다. 만 14세 미만인 것이 확인되면 그 정보를 지웁니다.</li>
            <li>LMS 연동·파일 업로드·캘린더·알림은 이용자가 켜거나 올릴 때만 처리합니다.</li>
          </List>
        </Section>

        <Section title="2. 외부 AI(Google Gemini) 처리">
          <p>다음 자료는 요건 추출·분류·요약을 위해 Google Gemini(Google Cloud)로 보내 처리합니다.</p>
          <List>
            <li>학교 공지의 본문·첨부(이용자와 상관없이, 공지를 가져오거나 내용이 바뀌었을 때)</li>
            <li>LearningX 과목 공지의 제목·본문(LearningX를 연결하면 동기화할 때 자동으로)</li>
            <li>이용자가 올린 포스터·강의계획서(올릴 때)</li>
            <li>강의자료 PDF(올려서 요약할 때)와 받아 둔 과목 공지 첨부(문서함에서 &quot;요약하기&quot;를 누를 때)</li>
            <li>준비하기의 서류 안내를 만들 때 공고 제목·주최와 서류 이름(청년정책은 공고의 제출 서류 안내 글)</li>
          </List>
          <p>
            <strong>프로필 값(성적·소득 등)은 외부 AI로 보내지 않습니다.</strong> 자격 판정은 서비스 코드가 직접 합니다. 청년정책의 자격
            요건도 코드로 바꾸며 AI로 보내지 않습니다.
          </p>
        </Section>

        <Section title="3. 보유 기간과 파기">
          <p>개인정보는 회원 탈퇴 때까지 보유합니다. 탈퇴하면 다음과 같이 처리합니다.</p>
          <List>
            <li>
              <strong>바로 지웁니다</strong>: 프로필과 동의 기록, 올린 파일과 받아 둔 공지 첨부, 강의계획서 일정, 강의자료 요약, LMS 토큰과 내
              과목·과제 기록, 판정 결과, 관심·숨김 표시, 준비 일정·플래너, 알림, 설정, 캘린더 등록 기록, 웹 푸시 구독, 이용 이벤트
            </li>
            <li>
              <strong>로그인 계정</strong>(이메일·이름·프로필 사진)도 지웁니다. 드물게 로그인 서버에 닿지 못해 계정이 남을 수 있는데, 보호책임자에게
              알려 주시면 지웁니다.
            </li>
            <li>
              <strong>Google 캘린더 접근 권한</strong>을 해제하고 저장한 토큰을 지웁니다. Google에 연결되지 않아도 토큰은 지웁니다.
            </li>
            <li>
              <strong>LearningX 개인 액세스 토큰</strong>은 서비스에 저장한 것을 지웁니다. 토큰 자체는 LearningX에서 계속 쓸 수 있으니, 더
              쓰지 않으면 LearningX 설정에서 직접 지워 주세요.
            </li>
            <li>
              <strong>이용자의 캘린더에 이미 등록된 일정</strong>은 이용자의 것이므로 그대로 둡니다. 필요하면 Google 캘린더에서 직접 지울
              수 있습니다.
            </li>
          </List>
          <p>다음은 이용자 표시를 지운 채 남습니다.</p>
          <List>
            <li>
              <strong>처리 기록</strong>: 처리 단계·소요 시간·비용과 그때의 처리 결과(포스터에서 읽은 글, 강의계획서에서 뽑은 과목명·일정,
              과목 공지 요약 등)
            </li>
            <li>
              이용자가 올린 포스터로 만든 <strong>공고 정보</strong>: 제목·주최·자격 요건과 근거 문장·필요 서류·포스터에서 읽은 글. 포스터
              파일은 지웁니다.
            </li>
            <li>같은 과목 수강생이 함께 쓰는 과목 공통 자료(주차 항목 제목, 과목 공지와 첨부 이름, 공지로 만든 공고)</li>
          </List>
          <p>서버 접속 기록과 로그인 기록은 탈퇴와 상관없이 수탁자(Supabase·Google Cloud·Vercel)의 보관 정책에 따라 일정 기간 뒤 지워집니다.</p>
          <p>
            캘린더를 연결할 때 처음과 다른 Google 계정을 고르면 그 계정은 연결하지 않고 로그아웃합니다. 다만 처음 쓰는 계정이었다면 그 계정의
            로그인 정보(이메일·이름·사진)가 로그인 서버에 남을 수 있습니다. 보호책임자에게 알려 주시면 지웁니다.
          </p>
        </Section>

        <Section title="4. Google 사용자 데이터 처리">
          <List>
            <li>로그인에는 Google의 기본 정보(이메일, 이름, 프로필 사진)만 받습니다.</li>
            <li>
              캘린더에는{" "}
              <code className="break-all rounded bg-[#f2f4f7] px-1 text-[12px]">https://www.googleapis.com/auth/calendar.events</code> 권한
              하나를 씁니다.
            </li>
            <li>
              이 권한은 로그인할 때가 아니라 캘린더를 처음 연결할 때 따로 요청합니다(설정의 캘린더 연결, 공고 마감일·강의계획서 일정의 캘린더
              등록).
            </li>
            <li>
              연결한 뒤에는 이용자가 고른 공고 마감일과 강의계획서 일정을 넣고, LMS 과제 마감은 설정의 자동 등록이 켜져 있으면(처음에는 켜져
              있습니다) 동기화할 때 넣고 마감이 바뀌면 옮깁니다.
            </li>
            <li>
              이 권한은 일정 읽기도 허용하지만, 서비스는 <strong>서비스가 넣은 일정을 추가·수정·삭제하는 데만</strong> 씁니다. 이용자의
              다른 일정을 읽지 않습니다.
            </li>
            <li>
              Google 사용자 데이터를 광고에 쓰거나 다른 곳에 팔거나 넘기지 않습니다. 사람이 그 데이터를 읽지 않습니다. 다만 이용자의 동의가
              있거나, 보안·법령상 필요한 경우는 예외입니다.
            </li>
            <li lang="en">
              UNIPIVOT&apos;s use and transfer to any other app of information received from Google APIs will adhere to{" "}
              <Out href="https://developers.google.com/terms/api-services-user-data-policy">Google API Services User Data Policy</Out>,
              including the Limited Use requirements.
            </li>
          </List>
        </Section>

        <Section title="5. 제3자 제공">
          <p>서비스는 이용자의 개인정보를 제3자에게 제공하지 않습니다. 공고 주최측에도 제공하지 않습니다.</p>
        </Section>

        <Section title="6. 처리 위탁과 국외 이전">
          <Table
            caption="처리 위탁과 처리 위치"
            head={["수탁자", "위탁 업무", "처리 위치"]}
            rows={[
              ["Supabase Inc.", "회원 인증, 데이터베이스, 파일 저장", "대한민국(서울)"],
              ["Google LLC (Google Cloud)", "API 서버 운영, 서버 기록 보관", "서버는 대한민국(서울), 서버 기록은 국외(미국 등)일 수 있음"],
              [
                "Google LLC (Gemini, Google Cloud)",
                "공고·과목 공지·업로드 문서의 요건 추출·분류·요약",
                "처리 위치를 정하지 않음 — 국외(미국 등)에서 처리될 수 있음",
              ],
              ["Vercel Inc.", "웹 화면 제공", "서버 함수는 대한민국(서울), 화면 파일 배포와 접속 기록은 국외(미국 등)"],
            ]}
          />
          <p>웹 푸시 알림은 이용자 브라우저의 푸시 서비스(예: Google, Apple, Mozilla)를 거쳐 전달됩니다. 알림 내용은 암호화해 보냅니다.</p>
          <p>국외 이전에 관한 사항은 다음과 같습니다.</p>
          <List>
            <li>
              <strong>이전 항목</strong>: 위 표의 위탁 업무에 필요한 자료. Gemini에는 2장의 자료만 보내고 프로필 값은 보내지 않습니다.
            </li>
            <li>
              <strong>이전 국가</strong>: Gemini는 처리 위치를 정하지 않아 미국 등 Google이 운영하는 국가에서 처리될 수 있습니다. Vercel은 미국
              등에서 화면 파일을 배포하고 접속 기록을 둡니다.
            </li>
            <li>
              <strong>이전 시기와 방법</strong>: 서비스를 이용할 때, 그리고 LearningX를 연결했다면 30분마다 하는 동기화 때 암호화된
              네트워크(HTTPS)로 전송합니다.
            </li>
            <li>
              <strong>보유 기간</strong>: 각 수탁자의 처리 정책에 따릅니다.
            </li>
            <li>
              <strong>수탁자 연락처</strong>: 각 회사의 개인정보 처리방침에 있습니다 —{" "}
              <Out href="https://policies.google.com/privacy">Google 개인정보처리방침</Out>,{" "}
              <Out href="https://vercel.com/legal/privacy-policy">Vercel 개인정보처리방침</Out>,{" "}
              <Out href="https://supabase.com/privacy">Supabase 개인정보처리방침</Out>
            </li>
            <li>
              <strong>거부 방법과 영향</strong>: 포스터·강의계획서·강의자료를 올리지 않고 LearningX를 연결하지 않으면 이용자 자료는 Gemini로
              가지 않습니다(학교 공지의 요건 추출은 이용자와 상관없이 합니다). 웹 화면 제공(Vercel)은 서비스 이용에 꼭 필요해서,
              원하지 않으면 탈퇴할 수 있습니다.
            </li>
          </List>
        </Section>

        <Section title="7. 안전성 확보 조치">
          <List>
            <li>LMS·Google 토큰은 암호화해 저장합니다.</li>
            <li>
              데이터베이스는 행 단위 접근 제어를 켜 두어 이용자가 자기 데이터에만 접근할 수 있고, 서버도 요청한 이용자의 데이터만 다룹니다.
            </li>
            <li>서버 비밀값은 Google Secret Manager에 보관합니다.</li>
            <li>통신은 암호화 연결(HTTPS·TLS)로 합니다.</li>
            <li>처리 기록에는 토큰·비밀값·프로필 값을 남기지 않습니다.</li>
          </List>
        </Section>

        <Section title="8. 쿠키와 브라우저 저장소">
          <List>
            <li>
              로그인 상태를 유지하는 쿠키(로그아웃하면 지웁니다)와 로그인하는 동안만 쓰는 확인용 쿠키를 씁니다. 광고·추적용 쿠키와 외부 분석
              도구는 쓰지 않습니다.
            </li>
            <li>
              웹 푸시를 위한 서비스 워커(앱을 열면 등록)와 푸시 구독(알림을 켤 때), 알림 안내를 닫았는지 같은 화면 설정(브라우저 탭을 닫으면
              지워짐)을 브라우저에 둡니다.
            </li>
            <li>브라우저 설정에서 쿠키를 막을 수 있지만, 그러면 로그인 상태가 유지되지 않아 서비스를 쓸 수 없습니다.</li>
          </List>
        </Section>

        <Section title="9. 이용자의 권리">
          <p>이용자는 언제든 자기 개인정보의 열람·정정·삭제·처리 정지를 요구할 수 있습니다.</p>
          <List>
            <li>프로필은 서비스 안에서 바로 고칠 수 있습니다.</li>
            <li>소득정보 동의는 철회할 수 있으며, 철회하면 해당 항목을 지웁니다.</li>
            <li>탈퇴는 설정 화면에서 할 수 있습니다.</li>
            <li>그 밖의 요청은 아래 보호책임자에게 연락하면 지체 없이 처리합니다.</li>
          </List>
        </Section>

        <Section title="10. 개인정보 보호책임자">
          <List>
            <li>
              이름: {OFFICER.name} ({OFFICER.role})
            </li>
            <li>
              이메일:{" "}
              <a href={`mailto:${OFFICER.email}`} className="font-semibold text-[#4f6ef7] underline-offset-2 hover:underline">
                {OFFICER.email}
              </a>
            </li>
          </List>
        </Section>

        <Section title="11. 권익침해 구제 방법">
          <p>개인정보 침해에 대한 신고나 상담이 필요하면 아래 기관에 문의할 수 있습니다.</p>
          <List>
            <li>
              개인정보 침해신고센터(한국인터넷진흥원): (국번 없이) 118, <Out href="https://privacy.kisa.or.kr">privacy.kisa.or.kr</Out>
            </li>
            <li>
              개인정보 분쟁조정위원회: 1833-6972, <Out href="https://www.kopico.go.kr">kopico.go.kr</Out>
            </li>
            <li>
              대검찰청: (국번 없이) 1301, <Out href="https://www.spo.go.kr">spo.go.kr</Out>
            </li>
            <li>
              경찰청: (국번 없이) 182, <Out href="https://ecrm.police.go.kr">ecrm.police.go.kr</Out>
            </li>
          </List>
        </Section>

        <Section title="12. 변경">
          <p>이 방침을 바꾸면 시행 7일 전부터 이 페이지에 바뀌는 내용과 시행일을 알립니다. 지난 버전은 이 페이지 아래에 남깁니다.</p>
          <p className="text-[13px] text-[#667085]">지난 버전: 없음(첫 버전)</p>
        </Section>

        <p className="mt-10 border-t border-[#e5e7eb] pt-5 text-[13px]">
          <Link href="/" className="font-semibold text-[#4f6ef7] underline-offset-2 hover:underline">
            UNIPIVOT으로 돌아가기
          </Link>
        </p>
      </article>
    </main>
  );
}
