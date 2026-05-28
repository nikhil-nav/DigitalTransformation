import { redirect } from "next/navigation";

import LoginForm from "@/components/LoginForm";
import { getSessionUser } from "@/lib/session";

export default async function LoginPage() {
  const user = await getSessionUser();
  if (user) {
    // trigger comment
    redirect("/");
  }

  return (
    <main className="login-main">
      <LoginForm />
    </main>
  );
}
