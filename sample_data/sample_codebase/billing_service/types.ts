/** Supported currency codes */
export type Currency = 'USD' | 'EUR' | 'GBP';

/** Status of a payment transaction */
export type PaymentStatus = 'pending' | 'completed' | 'failed' | 'refunded';

/** Billing interval for subscription plans */
export enum BillingInterval {
  MONTHLY = 'monthly',
  YEARLY = 'yearly',
}

/** Represents a single line item on an invoice */
export interface InvoiceItem {
  description: string;
  quantity: number;
  unitPrice: number;
}

/** Represents an invoice issued to a customer */
export interface Invoice {
  id: string;
  amount: number;
  currency: Currency;
  status: PaymentStatus;
  createdAt: Date;
  items: InvoiceItem[];
}

/** A stored payment method for a customer */
export interface PaymentMethod {
  type: 'credit_card' | 'debit_card' | 'bank_transfer';
  lastFour: string;
  expiryDate: string;
}

/** A recurring billing plan */
export interface BillingPlan {
  id: string;
  name: string;
  price: number;
  interval: BillingInterval;
}

/** Result returned after processing a payment */
export interface PaymentResult {
  success: boolean;
  transactionId: string | null;
  error?: string;
}

/** Configuration for the billing service */
export interface BillingConfig {
  apiKey: string;
  webhookUrl: string;
  testMode: boolean;
}
