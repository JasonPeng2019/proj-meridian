import React from 'react';
import { Slot } from '@radix-ui/react-slot';
import { cva } from 'class-variance-authority';
import { cn } from '../../lib/utils';

const buttonVariants = cva('ui-button inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-md text-sm font-medium transition-colors focus-visible:outline-none disabled:pointer-events-none disabled:opacity-50 [&_svg]:shrink-0', {
  variants: {
    variant: {
      default: 'ui-button-primary bg-primary text-primary-foreground hover:bg-primary/90',
      destructive: 'ui-button-destructive bg-destructive text-white',
      outline: 'ui-button-outline border border-input bg-background hover:bg-accent',
      secondary: 'ui-button-secondary bg-secondary text-secondary-foreground hover:bg-secondary/80',
      ghost: 'ui-button-ghost hover:bg-accent hover:text-accent-foreground',
      link: 'ui-button-link text-primary underline-offset-4 hover:underline',
    },
    size: {default: 'h-9 px-4 py-2', sm: 'h-8 px-3 text-xs', lg: 'h-10 px-6', icon: 'h-9 w-9 p-0'},
  },
  defaultVariants: {variant: 'default', size: 'default'},
});

const Button = React.forwardRef(({className, variant, size, asChild = false, type = 'button', ...props}, ref) => {
  const Comp = asChild ? Slot : 'button';
  return <Comp ref={ref} {...(!asChild ? {type} : {})} className={cn(buttonVariants({variant, size}), className)} {...props}/>;
});
Button.displayName = 'Button';
export {Button, buttonVariants};
