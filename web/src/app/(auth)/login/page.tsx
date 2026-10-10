"use client";

import { Suspense, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { createBrowserSupabase } from "@/lib/supabase/client";

const useMocks = process.env.NEXT_PUBLIC_USE_MOCKS === "true";

const errorMessages: Record<string, string> = {
  auth: "로그인을 마치지 못했어요. 다시 시도해 주세요.",
  missing_code: "로그인 정보가 없어요. 처음부터 다시 시도해 주세요.",
};

function GoogleMark() {
  return (
    <svg aria-hidden="true" width="18" height="18" viewBox="0 0 48 48">
      <path fill="#EA4335" d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z" />
      <path fill="#4285F4" d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z" />
      <path fill="#FBBC05" d="M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59s.27-3.14.76-4.59l-7.98-6.19C.92 16.46 0 20.12 0 24c0 3.88.92 7.54 2.56 10.78l7.97-6.19z" />
      <path fill="#34A853" d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.15 1.45-4.92 2.3-8.16 2.3-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z" />
    </svg>
  );
}

function LoginCard() {
  const router = useRouter();
  const errorCode = useSearchParams().get("error");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(
    errorCode ? (errorMessages[errorCode] ?? errorMessages.auth) : null,
  );

  const signIn = async () => {
    setPending(true);
    setError(null);
    if (useMocks) {
      router.push("/onboarding");
      return;
    }
    // 로그인은 기본 범위(이메일·프로필)만 받는다. 캘린더 권한은 처음 등록할 때 따로 받는다 (증분 승인)
    const { error: signInError } = await createBrowserSupabase().auth.signInWithOAuth({
      provider: "google",
      options: { redirectTo: `${window.location.origin}/auth/callback` },
    });
    if (signInError) {
      setError("Google 로그인을 시작하지 못했어요. 잠시 후 다시 시도해 주세요.");
      setPending(false);
    }
  };

  return (
    <section className="mx-auto w-full max-w-[440px] rounded-[18px] border border-[#e5e7eb] bg-white p-8 text-center max-[760px]:p-6">
      <p className="text-[32px] font-bold text-[#4f6ef7]">UNIPIVOT</p>
      <h1 className="mt-4 text-[20px] font-bold leading-[1.45]">
        지원할 수 있는 장학금·정책·공모전을 찾아 준비 일정까지 만들어요
      </h1>
      <button
        type="button"
        onClick={signIn}
        disabled={pending}
        className="mt-8 flex h-[48px] w-full items-center justify-center gap-3 rounded-[10px] border border-[#e5e7eb] bg-white text-[15px] font-semibold text-[#181a20] transition hover:bg-[#f7f8fa] disabled:cursor-not-allowed disabled:opacity-50"
      >
        <GoogleMark />
        {pending ? "Google로 이동 중" : "Google로 시작하기"}
      </button>
      <p className="mt-3 text-[12px] leading-5 text-[#667085]">
        Google 계정으로 로그인해요. 캘린더는 마감일을 처음 등록할 때 따로 연결해요.
      </p>
      {error && (
        <p role="alert" className="mt-4 rounded-[10px] bg-[#fef2f2] p-3 text-[13px] text-[#c53030]">
          {error}
        </p>
      )}
    </section>
  );
}

export default function LoginPage() {
  return (
    <Suspense>
      <LoginCard />
    </Suspense>
  );
}
