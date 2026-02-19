import { Invoice, PaymentMethod, BillingPlan, PaymentResult } from './types';

/** Default tax rate applied to invoices */
export const TAX_RATE = 0.08;

/**
 * Generates a unique transaction identifier.
 * This is a private helper and should not be exported.
 */
function generateTransactionId(): string {
  return `txn_${Date.now()}_${Math.random().toString(36).slice(2, 9)}`;
}

/**
 * Formats an amount into a human-readable currency string.
 * @param amount - The monetary amount to format.
 * @param currency - The ISO currency code.
 * @returns A formatted currency string.
 */
export function formatCurrency(amount: number, currency: string): string {
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency,
  }).format(amount);
}

/**
 * Validates that a payment method has the required fields and correct format.
 * @param method - The payment method to validate.
 * @returns True if the payment method is valid.
 */
export function validatePaymentMethod(method: PaymentMethod): boolean {
  const validTypes = ['credit_card', 'debit_card', 'bank_transfer'];
  if (!validTypes.includes(method.type)) return false;
  if (!/^\d{4}$/.test(method.lastFour)) return false;
  if (!/^\d{2}\/\d{2}$/.test(method.expiryDate)) return false;
  return true;
}

/** Service responsible for billing operations such as invoicing and payments. */
export class BillingService {
  private invoices: Invoice[] = [];

  /** Creates a new invoice from the given plan and returns it. */
  createInvoice(plan: BillingPlan, currency: string): Invoice {
    const invoice: Invoice = {
      id: `inv_${Date.now()}`,
      amount: plan.price,
      currency: currency as Invoice['currency'],
      status: 'pending',
      createdAt: new Date(),
      items: [{ description: plan.name, quantity: 1, unitPrice: plan.price }],
    };
    this.invoices.push(invoice);
    return invoice;
  }

  /** Processes a payment for the given invoice using the provided payment method. */
  processPayment(invoice: Invoice, method: PaymentMethod): PaymentResult {
    if (!validatePaymentMethod(method)) {
      return { success: false, transactionId: null, error: 'Invalid payment method' };
    }
    const transactionId = generateTransactionId();
    invoice.status = 'completed';
    return { success: true, transactionId };
  }

  /** Calculates the tax for a given subtotal using the default tax rate. */
  calculateTax(subtotal: number): number {
    return Math.round(subtotal * TAX_RATE * 100) / 100;
  }

  /** Returns the list of all invoices created through this service. */
  getInvoiceHistory(): Invoice[] {
    return [...this.invoices];
  }
}
