import React from 'react';
import * as DialogPrimitive from '@radix-ui/react-dialog';
import { X } from 'lucide-react';
import { cn } from '../../lib/utils';

const Dialog=DialogPrimitive.Root, DialogTrigger=DialogPrimitive.Trigger, DialogPortal=DialogPrimitive.Portal, DialogClose=DialogPrimitive.Close;
const DialogOverlay=React.forwardRef(({className,...props},ref)=><DialogPrimitive.Overlay ref={ref} className={cn('ui-dialog-overlay',className)} {...props}/>);
DialogOverlay.displayName='DialogOverlay';
const DialogContent=React.forwardRef(({className,children,showCloseButton=true,overlayClassName,...props},ref)=><DialogPortal><DialogOverlay className={overlayClassName}/><DialogPrimitive.Content ref={ref} className={cn('ui-dialog-content',className)} {...props}>{children}{showCloseButton&&<DialogPrimitive.Close className="ui-dialog-close" aria-label="Close"><X size={18}/></DialogPrimitive.Close>}</DialogPrimitive.Content></DialogPortal>);
DialogContent.displayName='DialogContent';
function DialogHeader({className,...props}){return <div className={cn('ui-dialog-header',className)} {...props}/>;}
function DialogFooter({className,...props}){return <div className={cn('ui-dialog-footer',className)} {...props}/>;}
const DialogTitle=React.forwardRef(({className,...props},ref)=><DialogPrimitive.Title ref={ref} className={cn('ui-dialog-title',className)} {...props}/>);
DialogTitle.displayName='DialogTitle';
const DialogDescription=React.forwardRef(({className,...props},ref)=><DialogPrimitive.Description ref={ref} className={cn('ui-dialog-description',className)} {...props}/>);
DialogDescription.displayName='DialogDescription';
export {Dialog,DialogTrigger,DialogPortal,DialogClose,DialogOverlay,DialogContent,DialogHeader,DialogFooter,DialogTitle,DialogDescription};
