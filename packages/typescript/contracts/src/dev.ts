import { z } from "zod";

export const demoUserSchema = z.object({
  subject: z.string(),
  display_name: z.string(),
  description: z.string(),
  roles: z.array(z.string()),
  tenant_id: z.string().uuid(),
  tenant_name: z.string(),
  workspace_id: z.string().uuid(),
});
export type DemoUser = z.infer<typeof demoUserSchema>;

export const devSessionSchema = z.object({
  token: z.string(),
  subject: z.string(),
  display_name: z.string(),
  roles: z.array(z.string()),
  tenant_id: z.string().uuid(),
  tenant_name: z.string(),
  workspace_id: z.string().uuid(),
  expires_at: z.string(),
});
export type DevSessionInfo = z.infer<typeof devSessionSchema>;
