import React from 'react';
import { cn } from '../../lib/utils';

const Input = React.forwardRef(({className, type = 'text', ...props}, ref) => <input type={type} ref={ref} className={cn('ui-input flex h-9 w-full min-w-0 rounded-md border border-input bg-background px-3 py-1 text-sm outline-none disabled:cursor-not-allowed disabled:opacity-50',className)} {...props}/>);
Input.displayName = 'Input';
export {Input};
