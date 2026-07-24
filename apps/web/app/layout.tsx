import type { Metadata } from "next";
import type { ReactNode } from "react";
import { Toaster } from "sonner";
import { AppFrame } from "../components/app-frame";
import { AuthProvider } from "../lib/auth/auth-context";
import "./globals.css";

export const metadata: Metadata = {
  title: "Digital Worker Platform",
  description:
    "Multi-tenant Digital Worker platform — tender & work operations",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="vi">
      <body className="min-h-screen bg-background antialiased">
        <AuthProvider>
          <AppFrame>{children}</AppFrame>
        </AuthProvider>
        <Toaster richColors position="bottom-right" />
      </body>
    </html>
  );
}
