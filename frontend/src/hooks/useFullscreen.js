import { useCallback, useEffect, useState } from 'react';

import styles from './useFullscreen.module.css';

export const FULLSCREEN_MODE = Object.freeze({
  BROWSER: 'browser',
  WINDOW: 'window'
});

function getFullscreenElement() {
  return document.fullscreenElement || document.webkitFullscreenElement || null;
}

function getRequestFullscreen(element) {
  return element?.requestFullscreen || element?.webkitRequestFullscreen;
}

function getExitFullscreen() {
  return document.exitFullscreen || document.webkitExitFullscreen;
}

/**
 * 统一管理两种全屏模式：
 * - browser：通过浏览器 Fullscreen API 展示 targetRef 指向的元素。
 * - window：通过状态控制当前窗口内的全屏样式。
 */
export function useFullscreen({ mode = FULLSCREEN_MODE.BROWSER, targetRef, onError } = {}) {
  const [isWindowFullscreen, setIsWindowFullscreen] = useState(false);
  const [isBrowserFullscreen, setIsBrowserFullscreen] = useState(false);
  const [isFallback, setIsFallback] = useState(false);

  const reportError = useCallback(
    error => {
      if (onError) {
        onError(error);
        return;
      }

      console.error('切换全屏失败', error);
    },
    [onError]
  );

  useEffect(() => {
    if (mode !== FULLSCREEN_MODE.BROWSER) return undefined;

    function syncBrowserFullscreen() {
      const fullscreenElement = getFullscreenElement();
      setIsBrowserFullscreen(fullscreenElement === targetRef?.current);
      if (fullscreenElement) setIsFallback(false);
    }

    syncBrowserFullscreen();
    document.addEventListener('fullscreenchange', syncBrowserFullscreen);
    document.addEventListener('webkitfullscreenchange', syncBrowserFullscreen);

    return () => {
      document.removeEventListener('fullscreenchange', syncBrowserFullscreen);
      document.removeEventListener('webkitfullscreenchange', syncBrowserFullscreen);
    };
  }, [mode, targetRef]);

  const isFullscreen =
    mode === FULLSCREEN_MODE.WINDOW ? isWindowFullscreen : isBrowserFullscreen || isFallback;
  const targetClassName =
    mode === FULLSCREEN_MODE.BROWSER
      ? [styles.browserTarget, isFallback && styles.windowTarget].filter(Boolean).join(' ')
      : isWindowFullscreen
        ? styles.windowTarget
        : undefined;

  const enterFullscreen = useCallback(async () => {
    if (mode === FULLSCREEN_MODE.WINDOW) {
      setIsWindowFullscreen(true);
      return true;
    }

    const target = targetRef?.current;
    if (!target) return false;

    try {
      const fullscreenElement = getFullscreenElement();
      if (fullscreenElement && fullscreenElement !== target) {
        const exitFullscreen = getExitFullscreen();
        await exitFullscreen?.call(document);
      }

      const requestFullscreen = getRequestFullscreen(target);
      if (!requestFullscreen) {
        setIsFallback(true);
        return true;
      }

      setIsFallback(false);
      await requestFullscreen.call(target);
      setIsBrowserFullscreen(getFullscreenElement() === target);
      return true;
    } catch (error) {
      reportError(error);
      return false;
    }
  }, [mode, reportError, targetRef]);

  const exitFullscreen = useCallback(async () => {
    if (mode === FULLSCREEN_MODE.WINDOW) {
      setIsWindowFullscreen(false);
      return true;
    }

    if (isFallback) {
      setIsFallback(false);
      return true;
    }

    try {
      if (getFullscreenElement() !== targetRef?.current) return false;

      const exitBrowserFullscreen = getExitFullscreen();
      if (!exitBrowserFullscreen) return false;

      await exitBrowserFullscreen.call(document);
      setIsBrowserFullscreen(false);
      return true;
    } catch (error) {
      reportError(error);
      return false;
    }
  }, [isFallback, mode, reportError, targetRef]);

  const toggleFullscreen = useCallback(
    () => (isFullscreen ? exitFullscreen() : enterFullscreen()),
    [enterFullscreen, exitFullscreen, isFullscreen]
  );

  useEffect(() => {
    const usesWindowOverlay = mode === FULLSCREEN_MODE.WINDOW || isFallback;
    if (!usesWindowOverlay || !isFullscreen) return undefined;

    function handleKeyDown(event) {
      if (event.key === 'Escape') exitFullscreen();
    }

    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [exitFullscreen, isFallback, isFullscreen, mode]);

  return {
    enterFullscreen,
    exitFullscreen,
    isFallback,
    isFullscreen,
    targetClassName,
    toggleFullscreen
  };
}

export function useBrowserFullscreen(targetRef, options) {
  return useFullscreen({ ...options, mode: FULLSCREEN_MODE.BROWSER, targetRef });
}

export function useWindowFullscreen(options) {
  return useFullscreen({ ...options, mode: FULLSCREEN_MODE.WINDOW });
}
