import React from 'react';
import { cva } from 'class-variance-authority';
import { cn } from '../../lib/utils';

const badgeVariants = cva('ui-badge inline-flex items-center rounded-md border px-2 py-0.5 text-xs font-medium', {
  variants: {variant: {
    default: 'ui-badge-primary border-transparent bg-primary text-primary-foreground',
    secondary: 'ui-badge-secondary border-transparent bg-secondary text-secondary-foreground',
    outline: 'ui-badge-outline border-border text-foreground',
    destructive: 'ui-badge-destructive border-transparent bg-destructive text-white',
  }}, defaultVariants: {variant: 'secondary'},
});
function Badge({className, variant, ...props}) { return <span className={cn(badgeVariants({variant}),className)} {...props}/>; }
export {Badge, badgeVariants};
