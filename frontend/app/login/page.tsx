import { redirect } from "next/navigation";

import LoginForm from "@/components/LoginForm";
import { getSessionUser } from "@/lib/session";

export default async function LoginPage() {
  const user = await getSessionUser();
  if (user) {
    // trigger
    redirect("/");
  }

  return (
    <main className="login-main">
      <img src="/navikenz_logo.png" alt="Navikenz" className="login-logo" />
      <LoginForm />
    </main>
  );
}
