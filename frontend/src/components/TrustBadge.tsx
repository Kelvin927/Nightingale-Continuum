import {
  Bot,
  CheckCircle2,
  CircleUserRound,
  History,
  ShieldCheck,
  UsersRound,
} from "lucide-react";

const labels: Record<string, string> = {
  ai_proposed: "AI proposed",
  clinician_confirmed: "Clinician confirmed",
  staff_verified: "Staff verified",
  human_authored: "Human authored",
  superseded: "Superseded",
};

export function TrustBadge({ state }: { state: string }) {
  const Icon =
    state === "ai_proposed"
      ? Bot
      : state === "clinician_confirmed"
        ? ShieldCheck
        : state === "staff_verified"
          ? UsersRound
          : state === "superseded"
            ? History
            : CircleUserRound;
  return (
    <span className={`trust-badge trust-${state.replaceAll("_", "-")}`}>
      <Icon aria-hidden="true" size={13} strokeWidth={2.2} />
      {labels[state] ?? state.replaceAll("_", " ")}
      {state === "clinician_confirmed" && (
        <CheckCircle2 aria-hidden="true" size={12} strokeWidth={2.4} />
      )}
    </span>
  );
}

