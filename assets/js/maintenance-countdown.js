(async function () {
    // En desarrollo local (localhost / 127.0.0.1) o modo dev, omitir mantenimiento para poder probar libremente
    const isLocal = window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1' || window.location.protocol === 'file:';
    const isDev = isLocal || window.__YAIRE_DEV_BYPASS__ || localStorage.getItem('yaire_dev_mode') === '1' || sessionStorage.getItem('yaire_dev_mode') === '1';
    const urlParams = new URLSearchParams(window.location.search);
    if (isDev || urlParams.get('dev') === '1' || urlParams.get('admin') === '1') {
        return;
    }

    // Fecha oficial de apertura: 21 de Noviembre de 2026 a las 00:00:00 (12:00 AM, Hora Venezuela UTC-4)
    const unlockDate = new Date('2026-11-21T00:00:00-04:00');
    if (urlParams.get('reset') === '1') {
        localStorage.clear();
        sessionStorage.clear();
    }
    const _FB = 'https://yaire-591ca-default-rtdb.firebaseio.com/config.json';

    function parseMaintTargetMs(maintDate) {
        if (!maintDate || typeof maintDate !== 'string') return null;
        const trimmed = maintDate.trim();
        if (!trimmed) return null;
        if (/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/.test(trimmed)) {
            const ms = Date.parse(trimmed + ':00-04:00');
            if (!Number.isNaN(ms)) return ms;
        }
        const fallback = Date.parse(trimmed);
        return Number.isNaN(fallback) ? null : fallback;
    }

    function getSyncedNowMs() {
        let offset = 0;
        try { offset = Number(localStorage.getItem('yaire_server_offset')) || 0; } catch (_) {}
        return Date.now() + offset;
    }

    function isAdminMaintenanceActive(fbCfg) {
        if (!fbCfg || fbCfg.mantenimiento !== true) return false;
        const openingMs = unlockDate.getTime();
        const nowMs = getSyncedNowMs();
        if (fbCfg.maintType === 'scheduled' && fbCfg.maintDate) {
            const targetMs = parseMaintTargetMs(fbCfg.maintDate);
            if (!targetMs || nowMs >= targetMs) return false;
            return targetMs > openingMs;
        }
        const updatedMs = fbCfg.lastUpdated ? Date.parse(fbCfg.lastUpdated) : 0;
        return updatedMs >= openingMs;
    }

    // Aviso fluido estilo OLED Monolith cuando el administrador activa mantenimiento con usuarios dentro
    function startMaintenanceCountdown(targetPage = 'mantenimiento.html') {
        if (!document.body) {
            window.addEventListener('DOMContentLoaded', () => startMaintenanceCountdown(targetPage), { once: true });
            return;
        }
        if (document.getElementById('maintenance-countdown-overlay')) return;

        if (typeof _stateInterval !== 'undefined') {
            clearInterval(_stateInterval);
        }

        const overlay = document.createElement('div');
        overlay.id = 'maintenance-countdown-overlay';
        overlay.style.cssText = 'position:fixed;inset:0;z-index:999999;display:flex;align-items:center;justify-content:center;background:rgba(0,0,0,0.78);backdrop-filter:blur(18px) saturate(160%);-webkit-backdrop-filter:blur(18px) saturate(160%);opacity:0;transition:opacity 280ms cubic-bezier(0.23,1,0.32,1);padding:20px;';

        overlay.innerHTML = `
            <div id="maintenance-card" style="position:relative;max-width:360px;width:100%;padding:32px 28px;border-radius:20px;background:#0b0b0a;border:1px solid rgba(247,244,238,0.12);text-align:center;color:#f7f4ee;transform:translateY(8px) scale(0.96);opacity:0;transition:transform 320ms cubic-bezier(0.23,1,0.32,1),opacity 280ms cubic-bezier(0.23,1,0.32,1);">
                <div style="width:44px;height:44px;margin:0 auto 18px;border-radius:50%;background:rgba(232,189,131,0.10);border:1px solid rgba(232,189,131,0.26);display:flex;align-items:center;justify-content:center;color:#e8bd83;">
                    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                        <circle cx="12" cy="12" r="9"></circle>
                        <path d="M12 7v5l3 2"></path>
                    </svg>
                </div>
                <h3 style="font-family:'Sebenta',Georgia,serif;font-weight:500;font-size:1.75rem;line-height:1.1;letter-spacing:-0.025em;color:#f7f4ee;margin:0 0 10px;">Breve pausa</h3>
                <p style="font-family:'Plus Jakarta Sans',-apple-system,BlinkMacSystemFont,sans-serif;font-size:0.9rem;line-height:1.55;color:rgba(244,239,231,0.70);margin:0 0 22px;">
                    28E entrará en mantenimiento en unos segundos. Guardando tu sesión…
                </p>
                <div id="maintenance-countdown-timer" style="font-family:'Plus Jakarta Sans',-apple-system,BlinkMacSystemFont,sans-serif;font-size:3.25rem;font-weight:600;line-height:1;letter-spacing:-0.03em;color:#e8bd83;font-variant-numeric:tabular-nums;font-feature-settings:'tnum' 1;">
                    5
                </div>
            </div>
        `;

        document.body.appendChild(overlay);

        requestAnimationFrame(() => {
            overlay.style.opacity = '1';
            const card = document.getElementById('maintenance-card');
            if (card) {
                card.style.transform = 'translateY(0) scale(1)';
                card.style.opacity = '1';
            }
        });

        let timeLeft = 5;
        const timerEl = document.getElementById('maintenance-countdown-timer');

        const countdownInterval = setInterval(() => {
            timeLeft--;
            if (timeLeft >= 1) {
                if (timerEl) {
                    timerEl.textContent = String(timeLeft);
                    if (timerEl.animate) {
                        timerEl.animate([
                            { transform: 'translateY(6px) scale(0.94)', opacity: 0.45, filter: 'blur(2px)' },
                            { transform: 'translateY(0) scale(1)', opacity: 1, filter: 'blur(0px)' }
                        ], {
                            duration: 280,
                            easing: 'cubic-bezier(0.23, 1, 0.32, 1)'
                        });
                    }
                }
            } else {
                clearInterval(countdownInterval);
                const card = document.getElementById('maintenance-card');
                if (card) {
                    card.style.transform = 'scale(0.96)';
                    card.style.opacity = '0';
                    card.style.transition = 'transform 220ms ease-out, opacity 220ms ease-out';
                }
                overlay.style.opacity = '0';
                setTimeout(() => {
                    window.location.replace(targetPage);
                }, 230);
            }
        }, 1000);
    }

    let _isInitialCheck = true;
    async function checkState() {
        if (localStorage.getItem('yaire_restore') === '1') {
            localStorage.removeItem('yaire_restore');
            _isInitialCheck = false;
            return;
        }
        try {
            const res = await fetch(_FB + '?nocache=' + Date.now());
            if (res.ok) {
                const fbCfg = await res.json();
                if (fbCfg) {
                    const oldStr = localStorage.getItem('yaire_config');
                    const newStr = JSON.stringify(fbCfg);
                    const maintActiveNow = isAdminMaintenanceActive(fbCfg);

                    if (oldStr && oldStr !== newStr) {
                        let oldCfg = null;
                        try { oldCfg = JSON.parse(oldStr); } catch (_) {}
                        localStorage.setItem('yaire_config', newStr);
                        window.dispatchEvent(new CustomEvent('yaire_config_updated', { detail: fbCfg }));

                        if (maintActiveNow && urlParams.get('dev') !== '1') {
                            const wasMaintBefore = isAdminMaintenanceActive(oldCfg);
                            if (!_isInitialCheck && !wasMaintBefore) {
                                startMaintenanceCountdown('mantenimiento.html');
                            } else {
                                window.location.replace('mantenimiento.html');
                            }
                        } else if (!_isInitialCheck && !sessionStorage.getItem('yaire_reloaded')) {
                            sessionStorage.setItem('yaire_reloaded', '1');
                            window.location.reload();
                        }
                        _isInitialCheck = false;
                        return;
                    } else if (!oldStr) {
                        localStorage.setItem('yaire_config', newStr);
                        window.dispatchEvent(new CustomEvent('yaire_config_updated', { detail: fbCfg }));
                    }

                    if (maintActiveNow && urlParams.get('dev') !== '1') {
                        window.location.replace('mantenimiento.html');
                        return;
                    }
                }
            }
        } catch (_) {}

        // Si aún no llegó la fecha oficial de apertura de la web (21 de noviembre de 2026)
        if (getSyncedNowMs() < unlockDate.getTime() && urlParams.get('dev') !== '1') {
            window.location.replace('mantenimiento.html');
        }
        _isInitialCheck = false;
    }

    await checkState();

    let _stateInterval = setInterval(() => {
        if (!document.hidden) checkState();
    }, 8000);
    document.addEventListener('visibilitychange', () => {
        if (!document.hidden) checkState();
    });
})();
