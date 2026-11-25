import { createContext, useContext } from 'react';
import type { ReactNode } from 'react';
import { createPortal } from 'react-dom';

/** Only the presentation moves. Route-owned controllers and inputs keep their lifetime. */
export const ApplicationHeaderHost = createContext<HTMLElement | null>(null);
export function PageHeader({ children }: Readonly<{ children: ReactNode }>) {
  const host = useContext(ApplicationHeaderHost);
  return host ? createPortal(children, host) : children;
}

/** Shared title and page actions for application workspaces. */
export function SectionPageHeader({
  title,
  subtitle,
  children,
}: Readonly<{ title: string; subtitle?: string; children?: ReactNode }>) {
  return (
    <PageHeader>
      <header className="section-page-heading">
        <div className="section-page-identity">
          <h1>{title}</h1>
          {subtitle && <p className="read-status">{subtitle}</p>}
        </div>
        {children && (
          <div className="section-page-actions" role="group" aria-label="页面操作">
            {children}
          </div>
        )}
      </header>
    </PageHeader>
  );
}
