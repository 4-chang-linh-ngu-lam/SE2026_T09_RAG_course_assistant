'use client';

import React, { useId } from 'react';

interface LumiWolfMascotProps {
  size?: number;
  className?: string;
}

/**
 * Animated Lumi school-vibe wolf mascot avatar with looping wave, blink, and ear wiggle.
 */
export function LumiWolfMascot({ size = 84, className = '' }: LumiWolfMascotProps) {
  const uid = useId().replace(/:/g, '');
  const bgId = `lumi-wolf-bg-${uid}`;
  const sweaterId = `lumi-wolf-sweater-${uid}`;
  const furId = `lumi-wolf-fur-${uid}`;
  const clipId = `lumi-wolf-clip-${uid}`;

  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 512 512"
      width={size}
      height={size}
      className={`lumi-wolf-svg ${className}`.trim()}
      role="img"
      aria-label="Linh thú Sói học đường Lumi đang vẫy tay chào"
    >
      <defs>
        <linearGradient id={bgId} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0%" stopColor="#eff6ff" />
          <stop offset="100%" stopColor="#dbeafe" />
        </linearGradient>
        <linearGradient id={sweaterId} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="#2563eb" />
          <stop offset="100%" stopColor="#1d4ed8" />
        </linearGradient>
        <linearGradient id={furId} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="#64748b" />
          <stop offset="100%" stopColor="#475569" />
        </linearGradient>
        <clipPath id={clipId}>
          <rect x="0" y="0" width="512" height="512" rx="112" />
        </clipPath>
      </defs>

      <g clipPath={`url(#${clipId})`}>
        <rect width="512" height="512" fill={`url(#${bgId})`} />
        <circle cx="256" cy="264" r="210" fill="#ffffff" opacity="0.55" />

        <path
          className="lumi-wolf-sparkle"
          d="M92 128 L97 141 L110 146 L97 151 L92 164 L87 151 L74 146 L87 141 Z"
          fill="#93c5fd"
        />
        <path
          className="lumi-wolf-sparkle-delay"
          d="M422 142 L426 152 L436 156 L426 160 L422 170 L418 160 L408 156 L418 152 Z"
          fill="#60a5fa"
        />
        <circle className="lumi-wolf-sparkle" cx="404" cy="108" r="5" fill="#93c5fd" />

        <path
          d="M96 512 C96 410, 160 368, 256 368 C352 368, 416 410, 416 512 Z"
          fill={`url(#${sweaterId})`}
        />
        <path
          d="M120 512 C126 430, 174 392, 256 392 C338 392, 386 430, 392 512"
          fill="none"
          stroke="#1e40af"
          strokeWidth="3"
          opacity="0.25"
        />

        <path d="M198 374 L256 468 L314 374 Z" fill="#ffffff" />
        <path
          d="M198 374 L228 424 L256 398 Z"
          fill="#f1f5f9"
          stroke="#cbd5e1"
          strokeWidth="2"
          strokeLinejoin="round"
        />
        <path
          d="M314 374 L284 424 L256 398 Z"
          fill="#f1f5f9"
          stroke="#cbd5e1"
          strokeWidth="2"
          strokeLinejoin="round"
        />

        <path d="M244 396 L268 396 L264 416 L248 416 Z" fill="#0f172a" />
        <path d="M248 416 L264 416 L272 478 L256 498 L240 478 Z" fill="#0f172a" />
        <path d="M245 436 L267 428 L269 440 L243 448 Z" fill="#60a5fa" />
        <path d="M242 462 L270 454 L271 465 L241 473 Z" fill="#60a5fa" />

        <circle cx="318" cy="436" r="14" fill="#1e3a8a" opacity="0.25" />
        <circle cx="318" cy="434" r="13" fill="#ffffff" />
        <path
          d="M318 424 L321 431 L328 434 L321 437 L318 444 L315 437 L308 434 L315 431 Z"
          fill="#2563eb"
        />

        <ellipse cx="256" cy="376" rx="44" ry="18" fill="#e2e8f0" />

        <g className="lumi-wolf-waving-arm">
          <path
            d="M366 456 C384 428, 404 396, 418 364 L452 378 C438 416, 416 450, 394 476 Z"
            fill={`url(#${sweaterId})`}
            stroke="#1e40af"
            strokeWidth="3"
            strokeLinejoin="round"
          />
          <path
            d="M415 366 L453 380 L458 368 L420 354 Z"
            fill="#ffffff"
            stroke="#cbd5e1"
            strokeWidth="2"
            strokeLinejoin="round"
          />
          <g transform="translate(442, 336) rotate(12)">
            <ellipse
              cx="-16"
              cy="-22"
              rx="7.5"
              ry="12"
              fill="#64748b"
              stroke="#334155"
              strokeWidth="3"
              transform="rotate(-14 -16 -22)"
            />
            <ellipse
              cx="0"
              cy="-26"
              rx="7.5"
              ry="13"
              fill="#64748b"
              stroke="#334155"
              strokeWidth="3"
            />
            <ellipse
              cx="16"
              cy="-21"
              rx="7.5"
              ry="12"
              fill="#64748b"
              stroke="#334155"
              strokeWidth="3"
              transform="rotate(14 16 -21)"
            />
            <ellipse
              cx="-24"
              cy="-4"
              rx="7"
              ry="10"
              fill="#64748b"
              stroke="#334155"
              strokeWidth="3"
              transform="rotate(-38 -24 -4)"
            />
            <ellipse
              cx="0"
              cy="0"
              rx="23"
              ry="21"
              fill="#64748b"
              stroke="#334155"
              strokeWidth="3"
            />
            <ellipse cx="0" cy="3" rx="11" ry="9" fill="#fecdd3" />
            <circle cx="-13" cy="-16" r="3.5" fill="#fecdd3" />
            <circle cx="0" cy="-20" r="3.8" fill="#fecdd3" />
            <circle cx="13" cy="-15" r="3.5" fill="#fecdd3" />
          </g>
        </g>

        <g className="lumi-wolf-head-bob">
          <path
            d="M148 206 L124 88 C122 76, 134 70, 144 78 L222 142 Z"
            fill={`url(#${furId})`}
            stroke="#334155"
            strokeWidth="4"
            strokeLinejoin="round"
          />
          <path d="M154 188 L139 106 L204 150 Z" fill="#fecdd3" />

          <g className="lumi-wolf-right-ear">
            <path
              d="M364 206 L388 88 C390 76, 378 70, 368 78 L290 142 Z"
              fill={`url(#${furId})`}
              stroke="#334155"
              strokeWidth="4"
              strokeLinejoin="round"
            />
            <path d="M358 188 L373 106 L308 150 Z" fill="#fecdd3" />
          </g>

          <path
            d="M256 122 C316 122, 368 158, 378 214 L396 232 C402 238, 398 248, 386 250 L396 266 C400 274, 390 284, 374 282 C362 338, 314 374, 256 374 C198 374, 150 338, 138 282 C122 284, 112 274, 116 266 L126 250 C114 248, 110 238, 116 232 L134 214 C144 158, 196 122, 256 122 Z"
            fill={`url(#${furId})`}
            stroke="#334155"
            strokeWidth="4"
            strokeLinejoin="round"
          />

          <path
            d="M236 126 C242 104, 256 100, 260 118 C268 104, 282 112, 276 130 C264 124, 248 124, 236 126 Z"
            fill="#64748b"
            stroke="#334155"
            strokeWidth="3.5"
            strokeLinejoin="round"
          />

          <path
            d="M256 208 C276 208, 294 226, 314 230 C342 234, 366 254, 366 282 C366 332, 318 370, 256 370 C194 370, 146 332, 146 282 C146 254, 170 234, 198 230 C218 226, 236 208, 256 208 Z"
            fill="#f8fafc"
          />

          <path
            d="M182 186 Q202 174 222 184"
            fill="none"
            stroke="#f8fafc"
            strokeWidth="6"
            strokeLinecap="round"
            opacity="0.9"
          />
          <path
            d="M290 184 Q310 174 330 186"
            fill="none"
            stroke="#f8fafc"
            strokeWidth="6"
            strokeLinecap="round"
            opacity="0.9"
          />

          <g className="lumi-wolf-eye-blink">
            <ellipse cx="204" cy="222" rx="16" ry="19" fill="#0f172a" />
            <circle cx="210" cy="215" r="6" fill="#ffffff" />
            <circle cx="198" cy="228" r="2.8" fill="#ffffff" opacity="0.85" />

            <ellipse cx="308" cy="222" rx="16" ry="19" fill="#0f172a" />
            <circle cx="314" cy="215" r="6" fill="#ffffff" />
            <circle cx="302" cy="228" r="2.8" fill="#ffffff" opacity="0.85" />
          </g>

          <ellipse cx="170" cy="264" rx="18" ry="10" fill="#fda4af" opacity="0.55" />
          <ellipse cx="342" cy="264" rx="18" ry="10" fill="#fda4af" opacity="0.55" />

          <g stroke="#0f172a" strokeWidth="5.5" fill="none" strokeLinecap="round">
            <circle cx="204" cy="222" r="34" fill="#ffffff" fillOpacity="0.08" />
            <circle cx="308" cy="222" r="34" fill="#ffffff" fillOpacity="0.08" />
            <path d="M238 220 Q256 212 274 220" />
            <path d="M150 218 L170 220" />
            <path d="M342 220 L362 218" />
          </g>
          <path
            d="M184 204 L196 196"
            stroke="#ffffff"
            strokeWidth="3.5"
            strokeLinecap="round"
            opacity="0.65"
          />
          <path
            d="M288 204 L300 196"
            stroke="#ffffff"
            strokeWidth="3.5"
            strokeLinecap="round"
            opacity="0.65"
          />

          <path
            d="M240 258 C240 250, 272 250, 272 258 C272 268, 262 277, 256 277 C250 277, 240 268, 240 258 Z"
            fill="#0f172a"
          />
          <ellipse cx="251" cy="256" rx="5.5" ry="2.5" fill="#64748b" />

          <line
            x1="256"
            y1="277"
            x2="256"
            y2="290"
            stroke="#0f172a"
            strokeWidth="4"
            strokeLinecap="round"
          />

          <path
            d="M220 288 Q238 300 256 290 Q274 300 292 288"
            fill="none"
            stroke="#0f172a"
            strokeWidth="4.5"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
          <path
            d="M226 291 C230 326, 282 326, 286 291 Q271 299 256 291 Q241 299 226 291 Z"
            fill="#9f1239"
            stroke="#0f172a"
            strokeWidth="4"
            strokeLinejoin="round"
          />
          <path
            d="M240 309 C246 300, 266 300, 272 309 C266 320, 246 320, 240 309 Z"
            fill="#fb7185"
          />
        </g>
      </g>
    </svg>
  );
}

