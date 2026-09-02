/**
 * LoginPage — login and registration forms.
 * @module components/LoginPage
 */
import React, { useState } from "react";
import { Box, Flex, Text, Button, TextField, Callout } from "@radix-ui/themes";
import { SquaresFour, Info } from "@phosphor-icons/react";
import { useAuth } from "../hooks/useAuth";
import * as api from "../api";

type Mode = "login" | "register";

export function LoginPage({
  onSuccess,
}: { onSuccess?: () => void } = {}): React.ReactElement {
  const { login, refresh } = useAuth();
  const [mode, setMode] = useState<Mode>("login");
  const [username, setUsername] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [successMsg, setSuccessMsg] = useState("");

  const reset = (next: Mode): void => {
    setMode(next);
    setError("");
    setSuccessMsg("");
    setUsername("");
    setEmail("");
    setPassword("");
  };

  const handleSubmit = async (e: React.FormEvent): Promise<void> => {
    e.preventDefault();
    setError("");
    setSuccessMsg("");
    setLoading(true);

    try {
      if (mode === "login") {
        await login(username, password);
        onSuccess?.();
      } else {
        const result = await api.authRegister({ username, email, password });
        if (result.user.role === "admin") {
          // First user — auto-admin, cookie already set, just refresh auth state
          await refresh();
          onSuccess?.();
        } else {
          // Pending user — show message and switch to login tab
          setSuccessMsg(
            result.message ?? "Registration successful. Await admin approval.",
          );
          reset("login");
        }
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong");
    } finally {
      setLoading(false);
    }
  };

  return (
    <Flex
      align="center"
      justify="center"
      style={{ minHeight: "100vh", background: "var(--gray-a2)" }}
    >
      <Box
        style={{
          width: "100%",
          maxWidth: 380,
          background: "var(--color-panel-solid)",
          border: "1px solid var(--gray-a4)",
          borderRadius: "var(--radius-4)",
          padding: "32px 28px",
          boxShadow: "0 4px 24px var(--gray-a4)",
        }}
      >
        {/* Logo */}
        <Flex align="center" gap="2" mb="6">
          <Box
            style={{
              width: 38,
              height: 38,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              borderRadius: 12,
              background:
                "linear-gradient(135deg, var(--blue-9), var(--violet-9))",
              boxShadow: "0 10px 24px rgba(59, 130, 246, 0.28)",
            }}
          >
            <SquaresFour size={20} weight="fill" style={{ color: "#fff" }} />
          </Box>
          <Text size="5" weight="bold">
            TeamTracker
          </Text>
        </Flex>

        <Text size="4" weight="medium" mb="4" style={{ display: "block" }}>
          {mode === "login" ? "Sign in" : "Create account"}
        </Text>

        {successMsg && (
          <Callout.Root color="green" mb="3">
            <Callout.Icon>
              <Info size={16} />
            </Callout.Icon>
            <Callout.Text>{successMsg}</Callout.Text>
          </Callout.Root>
        )}

        <form onSubmit={handleSubmit}>
          <Flex direction="column" gap="3">
            <Box>
              <Text as="label" size="2" weight="medium" htmlFor="auth-username">
                Username
              </Text>
              <TextField.Root
                id="auth-username"
                mt="1"
                placeholder="your_username"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                autoComplete="username"
                required
              />
            </Box>

            {mode === "register" && (
              <Box>
                <Text as="label" size="2" weight="medium" htmlFor="auth-email">
                  Email
                </Text>
                <TextField.Root
                  id="auth-email"
                  mt="1"
                  type="email"
                  placeholder="you@example.com"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  autoComplete="email"
                  required
                />
              </Box>
            )}

            <Box>
              <Text as="label" size="2" weight="medium" htmlFor="auth-password">
                Password
              </Text>
              <TextField.Root
                id="auth-password"
                mt="1"
                type="password"
                placeholder={
                  mode === "register" ? "Min 8 characters" : "••••••••"
                }
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoComplete={
                  mode === "login" ? "current-password" : "new-password"
                }
                required
              />
            </Box>

            {error && (
              <Text size="2" color="red">
                {error}
              </Text>
            )}

            <Button
              type="submit"
              loading={loading}
              style={{ width: "100%", marginTop: 4 }}
            >
              {mode === "login" ? "Sign in" : "Register"}
            </Button>
          </Flex>
        </form>

        <Flex justify="center" mt="4">
          <Text size="2" color="gray">
            {mode === "login"
              ? "Don't have an account? "
              : "Already have an account? "}
            <Button
              variant="ghost"
              size="1"
              onClick={() => reset(mode === "login" ? "register" : "login")}
              style={{ cursor: "pointer" }}
            >
              {mode === "login" ? "Register" : "Sign in"}
            </Button>
          </Text>
        </Flex>
      </Box>
    </Flex>
  );
}
