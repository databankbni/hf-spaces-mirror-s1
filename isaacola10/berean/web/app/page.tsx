import VerseFinder from "./VerseFinder";
import AuthGate from "./components/AuthGate";

export default function Home() {
  return (
    <AuthGate>
      <main className="flex flex-1 flex-col items-center px-5 py-10 sm:py-14">
        <header className="mb-8 text-center">
          <h1 className="bg-gradient-to-r from-violet-600 via-fuchsia-500 to-pink-500 bg-clip-text text-4xl font-extrabold tracking-tight text-transparent sm:text-5xl dark:from-violet-400 dark:via-fuchsia-400 dark:to-pink-400">
            Verseo
          </h1>
          <p className="mx-auto mt-3 max-w-md text-balance text-slate-500 dark:text-slate-400">
            Speak, type, or ask a question — find the closest scriptures across
            translations and languages.
          </p>
        </header>

        <VerseFinder />

        <footer className="mt-12 text-center text-xs text-slate-400">
          Created by Isaac
        </footer>
      </main>
    </AuthGate>
  );
}
