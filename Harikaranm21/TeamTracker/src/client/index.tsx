/**
 * Client entry point — mounts the React app with Radix Themes and AuthProvider.
 */
import React from "react";
import { createRoot } from "react-dom/client";
import { Theme } from "@radix-ui/themes";
import "@radix-ui/themes/styles.css";
import "./index.css";
import App from "./App";
import { AuthProvider } from "./hooks/useAuth";

const container = document.getElementById("root");
if (!container) throw new Error("Root element not found");

createRoot(container).render(
  <Theme
    appearance="light"
    accentColor="blue"
    grayColor="slate"
    radius="large"
    scaling="100%"
  >
    <AuthProvider>
      <App />
    </AuthProvider>
  </Theme>,
);
