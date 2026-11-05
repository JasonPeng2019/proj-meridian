import React from 'react';
import * as TabsPrimitive from '@radix-ui/react-tabs';
import { cn } from '../../lib/utils';

const Tabs = TabsPrimitive.Root;
const TabsList = React.forwardRef(({className,...props},ref)=><TabsPrimitive.List ref={ref} className={cn('ui-tabs-list inline-flex items-center gap-1 rounded-lg bg-muted p-1 text-muted-foreground',className)} {...props}/>);
TabsList.displayName = 'TabsList';
const TabsTrigger = React.forwardRef(({className,...props},ref)=><TabsPrimitive.Trigger ref={ref} className={cn('ui-tabs-trigger inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-md px-3 py-2 text-sm font-medium outline-none disabled:pointer-events-none disabled:opacity-50 data-[state=active]:bg-background data-[state=active]:text-foreground',className)} {...props}/>);
TabsTrigger.displayName = 'TabsTrigger';
const TabsContent = React.forwardRef(({className,...props},ref)=><TabsPrimitive.Content ref={ref} className={cn('ui-tabs-content outline-none',className)} {...props}/>);
TabsContent.displayName = 'TabsContent';
export {Tabs,TabsList,TabsTrigger,TabsContent};
