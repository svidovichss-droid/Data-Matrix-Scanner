# Workspace

## Overview

pnpm workspace monorepo using TypeScript. Each package manages its own dependencies.

## Stack

- **Monorepo tool**: pnpm workspaces
- **Node.js version**: 24
- **Package manager**: pnpm
- **TypeScript version**: 5.9
- **API framework**: Express 5
- **Database**: PostgreSQL + Drizzle ORM
- **Validation**: Zod (`zod/v4`), `drizzle-zod`
- **API codegen**: Orval (from OpenAPI spec)
- **Build**: esbuild (CJS bundle)

## Key Commands

- `pnpm run typecheck` — full typecheck across all packages
- `pnpm run build` — typecheck + build all packages
- `pnpm --filter @workspace/api-spec run codegen` — regenerate API hooks and Zod schemas from OpenAPI spec
- `pnpm --filter @workspace/db run push` — push DB schema changes (dev only)
- `pnpm --filter @workspace/api-server run dev` — run API server locally

See the `pnpm-workspace` skill for workspace structure, TypeScript setup, and package details.

## Artifacts

### DataMatrix Quality Scanner (`artifacts/datamatrix-scanner`)
- **Purpose**: Web application for DataMatrix barcode quality assessment per ГОСТ Р 57302-2016 / ISO/IEC 15415
- **Authors**: Александр Свидович, Алексей Петляков
- **Tech**: React + Vite, @zxing/browser (DataMatrix decoding), Web Audio API (sound feedback)
- **Preview path**: `/`
- **Features**:
  - Live camera capture with auto-detect (prefers high-resolution/high-FPS cameras)
  - DataMatrix auto-decode via @zxing/browser
  - Quality analysis: 8 parameters (SC, MOD, RM, FPD, ANU, GNU, UEC, PG) per ГОСТ Р 57302-2016
  - Grades A–F with sound feedback:
    - A, B: single double-beep
    - C: two beeps
    - D: 4-tone alternating siren
    - F: 8-tone alarm siren
  - History log of up to 50 scans
  - Camera selection (auto-selects last camera = typically best quality)
  - FPS counter
  - Sound on/off toggle
