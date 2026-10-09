import {createContext,useContext} from 'react';
import type {ReactNode} from 'react';
import {createPortal} from 'react-dom';

/** Only the presentation moves. Route-owned controllers and inputs keep their lifetime. */
export const ApplicationHeaderHost=createContext<HTMLElement|null>(null);
export function PageHeader({children}:Readonly<{children:ReactNode}>){
  const host=useContext(ApplicationHeaderHost);
  return host?createPortal(children,host):children;
}
