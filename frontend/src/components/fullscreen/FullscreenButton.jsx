import { Maximize2, Minimize2 } from 'lucide-react';

import { Button } from '@/shadcn/components/ui/button.jsx';
import { cn } from '@/shadcn/lib/utils.js';
import { FULLSCREEN_MODE } from '@/hooks/useFullscreen.js';

import styles from './FullscreenButton.module.css';

export default function FullscreenButton({
  className,
  isFullscreen,
  mode = FULLSCREEN_MODE.BROWSER,
  onToggle,
  ...props
}) {
  return (
    <Button
      {...props}
      aria-pressed={isFullscreen}
      className={cn('dashboard-ghost-button', styles.button, className)}
      onClick={onToggle}
      size="icon-lg"
      type="button"
      variant="outline"
    >
      {isFullscreen ? <Minimize2 size={18} /> : <Maximize2 size={18} />}
    </Button>
  );
}
