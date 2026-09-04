import { DAY_KINDS, FLASH_TENANT } from "@/lib/flash/kinds";

import styles from "./flash.module.css";

export function FlashTopbar({ today }: { today: string }) {
  return (
    <div className={styles.topbar}>
      <div>
        <div className={styles.route}>FLASH</div>
        <div className={styles.routeSub}>agent news flash</div>
      </div>
      <div className={styles.meta}>
        <div>
          <span className={styles.lbl}>Tenant</span>
          <span className={styles.metaValue}>{FLASH_TENANT}</span>
        </div>
        <div>
          <span className={styles.lbl}>Phases</span>
          <span className={styles.metaValue}>{DAY_KINDS.join(" · ")}</span>
        </div>
        <div>
          <span className={styles.lbl}>Today</span>
          <span className={styles.metaValue}>{today}</span>
        </div>
      </div>
    </div>
  );
}
