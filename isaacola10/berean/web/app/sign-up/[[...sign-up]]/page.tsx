import { SignUp } from "@clerk/nextjs";

export default function SignUpPage() {
  return (
    <main className="flex flex-1 items-center justify-center px-5 py-16">
      <SignUp
        appearance={{
          elements: {
            rootBox: "w-full max-w-md",
            card: "rounded-3xl border border-white/60 shadow-lg dark:border-white/10",
          },
        }}
      />
    </main>
  );
}
