import { VissetPlayer } from './player';

export { TraceModel } from './model';
export type * from './types';
export { VissetPlayer };

if (typeof customElements !== 'undefined' && !customElements.get('visset-player')) {
  customElements.define('visset-player', VissetPlayer);
}

declare global {
  interface HTMLElementTagNameMap {
    'visset-player': VissetPlayer;
  }
}
