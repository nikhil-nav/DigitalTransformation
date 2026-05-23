import { redirect } from "next/navigation";

import LogoutButton from "@/components/LogoutButton";
import { getSessionUser } from "@/lib/session";

export default async function AppLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const user = await getSessionUser();
  if (!user) {
    redirect("/login");
  }

  return (
    <>
      <header className="app-header">
        <img src="/navikenz_logo.png" alt="Navikenz" className="app-logo" />
        <span className="app-header-title">
          Navigate- Digital Transformation Reimagined
        </span>
        <span className="app-header-user">
          Signed in as <strong>{user.username}</strong>
        </span>
        <LogoutButton />
      </header>
      <main className="app-main">{children}</main>
    </>
  );
}
