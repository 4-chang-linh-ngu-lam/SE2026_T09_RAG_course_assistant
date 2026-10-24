'use client';

import { forwardRef, type ComponentProps } from 'react';
import NextLink, { useLinkStatus } from 'next/link';
import './navigation-feedback.css';

export type NavigationLinkProps = ComponentProps<typeof NextLink>;

function NavigationLinkStatus() {
  const status = useLinkStatus();
  const pending = Boolean(status?.pending);

  return (
    <span
      className="lumi-navigation__status"
      data-pending={pending ? 'true' : 'false'}
      aria-hidden={!pending}
    >
      <span
        className={`lumi-navigation__spinner ${pending ? 'lumi-navigation__spinner--visible' : ''}`}
        aria-hidden="true"
      />
      {pending && (
        <span className="sr-only" role="status" aria-live="polite">
          Đang tải trang...
        </span>
      )}
    </span>
  );
}

export const NavigationLink = forwardRef<HTMLAnchorElement, NavigationLinkProps>(
  function NavigationLink({ children, className, ...restProps }, ref) {
    const combinedClassName = className
      ? `lumi-navigation ${className}`
      : 'lumi-navigation';

    return (
      <NextLink ref={ref} className={combinedClassName} {...restProps}>
        {children}
        <NavigationLinkStatus />
      </NextLink>
    );
  }
);

NavigationLink.displayName = 'NavigationLink';

export default NavigationLink;
