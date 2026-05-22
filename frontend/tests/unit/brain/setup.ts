import { vi } from 'vitest';

vi.mock('@/api/client', () => ({
  requestJson: vi.fn(),
}));
