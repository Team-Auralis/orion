"use client";

import { useId } from "react";
import styles from "./Aura.module.css";

export type AuraState =
  | "IDLE" | "LISTENING" | "ANALYZING" | "COORDINATING" | "ALERT"
  | "DEGRADED" | "RECOVERING" | "SAFE" | "HUMAN_REVIEW" | "OFFLINE";

export type AuraTheme = "dark" | "light" | "mono";

export interface AuraProps {
  state?: AuraState;
  size?: number | string;
  theme?: AuraTheme;
  intensity?: "low" | "normal" | "high";
  animated?: boolean;
  frozen?: boolean;
  className?: string;
}

const descriptions: Record<AuraState, string> = {
  IDLE: "ORION is healthy and waiting.",
  LISTENING: "ORION is receiving information.",
  ANALYZING: "ORION is processing incoming information.",
  COORDINATING: "ORION subsystems are coordinating.",
  ALERT: "ORION has detected a critical incident requiring attention.",
  DEGRADED: "ORION is operating with reduced capability.",
  RECOVERING: "ORION is restoring normal operation.",
  SAFE: "ORION is stable and the active incident is resolved.",
  HUMAN_REVIEW: "ORION requires authorized human review.",
  OFFLINE: "ORION cannot reach the relevant subsystem.",
};

/**
 * Presentation-only system presence. AURA intentionally never makes or
 * authorizes operational decisions; callers supply a display state.
 */
export function Aura({
  state = "IDLE", size = 96, theme = "dark", intensity = "normal",
  animated = true, frozen = false, className = "",
}: AuraProps) {
  const titleId = useId();
  const isAnimated = animated && !frozen;
  const style = typeof size === "number" ? { width: size, height: size } : { width: size, height: size };
  const accessibleLabel = `AURA: ${descriptions[state]}`;

  return (
    <svg
      className={`${styles.aura} ${styles[`state${state}`]} ${styles[`theme${theme}`]} ${styles[`intensity${intensity}`]} ${isAnimated ? styles.animated : styles.frozen} ${className}`}
      style={style}
      viewBox="0 0 120 120"
      role="img"
      aria-labelledby={titleId}
      aria-label={accessibleLabel}
      data-aura-state={state}
    >
      <title id={titleId}>{accessibleLabel}</title>
      <g className={styles.field}>
        <path className={styles.outer} d="M60 7 105 33v54L60 113 15 87V33Z" />
        <path className={styles.inner} d="M60 21 92 40v40L60 99 28 80V40Z" />
        <path className={styles.axis} d="M19 60h82M60 19v82" />
      </g>
      <g className={styles.core}>
        <path d="M60 37 74 54 60 60 46 54Z" />
        <path d="M60 83 46 66 60 60 74 66Z" />
        <circle className={styles.heart} cx="60" cy="60" r="4" />
      </g>
      <g className={styles.navigation}>
        <circle className={styles.navigatorA} cx="60" cy="15" r="3" />
        <rect className={styles.navigatorB} x="57.5" y="102" width="5" height="5" rx="1" />
      </g>
      <g className={styles.reviewMark} aria-hidden="true"><path d="M60 44v19M60 74v2" /></g>
      <g className={styles.offlineMark} aria-hidden="true"><path d="m43 43 34 34" /></g>
      <g className={styles.degradedGap} aria-hidden="true"><path d="M99 42 105 45v30l-6 3" /></g>
    </svg>
  );
}

export function auraDescription(state: AuraState): string {
  return descriptions[state];
}
