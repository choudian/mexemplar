import crypto from "node:crypto";

export interface CredentialSnapshot {
  present: boolean;
  fingerprint: string | null;
}

export class CredentialMutationAudit {
  private mutations = 0;

  recordMutationAttempt(): void {
    this.mutations += 1;
  }

  get mutationCount(): number {
    return this.mutations;
  }

  assertClean(): void {
    if (this.mutations !== 0) throw new Error("credential_mutation_attempted");
  }
}

export function credentialFingerprint(secret: string | null | undefined): CredentialSnapshot {
  if (!secret) return { present: false, fingerprint: null };
  return {
    present: true,
    fingerprint: crypto.createHash("sha256").update(secret).digest("hex"),
  };
}
