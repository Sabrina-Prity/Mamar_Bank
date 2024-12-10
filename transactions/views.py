from django.shortcuts import render

# Create your views here.
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.urls import reverse_lazy
from django.utils import timezone
from django.shortcuts import get_object_or_404, redirect
from django.views import View
from django.http import HttpResponse
from django.views.generic import CreateView, ListView
from transactions.constants import DEPOSIT, WITHDRAWAL,LOAN, LOAN_PAID
from datetime import datetime
from django.db.models import Sum
from django.core.mail import EmailMessage, EmailMultiAlternatives
from django.template.loader import render_to_string
from transactions.forms import (
    DepositForm,
    WithdrawForm,
    LoanRequestForm,
)
from transactions.models import Transaction
from accounts.models import UserBankAccount
from .forms import TransferForm

class TransactionCreateMixin(LoginRequiredMixin, CreateView):
    template_name = 'transactions/transaction_form.html'
    model = Transaction
    title = ''
    success_url = reverse_lazy('transaction_report')

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs.update({
            'account': self.request.user.account
        })
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs) # template e context data pass kora
        context.update({
            'title': self.title
        })

        return context


def send_transaction_email(user, amount, subject, template):
    message = render_to_string(template,{
        'user' : user,
        'amount' : amount,
    })
    send_email = EmailMultiAlternatives(subject, '', to=[user.email])
    send_email.attach_alternative(message, "text/html")
    send_email.send()



class DepositMoneyView(TransactionCreateMixin):
    form_class = DepositForm
    title = 'Deposit'

    def get_initial(self):
        initial = {'transaction_type': DEPOSIT}
        return initial

    def form_valid(self, form):
        amount = form.cleaned_data.get('amount')
        account = self.request.user.account
    

        # Check if the bank is bankrupt (if the account is marked as bankrupt)
        if account.bankrupt:
            messages.error(self.request, "The bank is bankrupt. You cannot deposit money.")
            return super().form_invalid(form)

        # Proceed with the deposit if not bankrupt
        account.balance += amount
        account.save(update_fields=['balance'])

        messages.success(self.request, f'{"{:,.2f}".format(amount)}$ was deposited to your account successfully')
        send_transaction_email(self.request.user, amount, "Deposit Message", "transactions/deposit_email.html")
        return super().form_valid(form)


class WithdrawMoneyView(TransactionCreateMixin):
    form_class = WithdrawForm
    title = 'Withdraw Money'

    def get_initial(self):
        initial = {'transaction_type': WITHDRAWAL}
        return initial

    def form_valid(self, form):
        amount = form.cleaned_data.get('amount')
        account = self.request.user.account

        # Check if the bank is bankrupt (if the account is marked as bankrupt)
        if account.bankrupt:
            messages.error(self.request, "The bank is bankrupt. You cannot withdraw money.")
            return super().form_invalid(form)  # Don't process further if bankrupt

        # Check if user has sufficient balance
        if account.balance < amount:
            messages.error(self.request, "Insufficient funds to complete the withdrawal.")
            return super().form_invalid(form)

        # Proceed with the withdrawal if not bankrupt
        account.balance -= amount
        account.save(update_fields=['balance'])

        messages.success(self.request, f'Successfully withdrawn {"{:,.2f}".format(amount)}$ from your account')
        send_transaction_email(self.request.user, amount, "Withdrawal Message", "transactions/withdraw_email.html")
        return super().form_valid(form)
    

class LoanRequestView(TransactionCreateMixin):
    form_class = LoanRequestForm
    title = 'Request For Loan'

    def get_initial(self):
        initial = {'transaction_type': LOAN}
        return initial

    def form_valid(self, form):
        amount = form.cleaned_data.get('amount')
        current_loan_count = Transaction.objects.filter(
            account=self.request.user.account,transaction_type=3,loan_approve=True).count()
        if current_loan_count >= 3:
            return HttpResponse("You have cross the loan limits")
        messages.success(
            self.request,
            f'Loan request for {"{:,.2f}".format(float(amount))}$ submitted successfully'
        )
        send_transaction_email(self.request.user, amount, "Loan Request Message", "transactions/loan_email.html")
        return super().form_valid(form)
    
class TransactionReportView(LoginRequiredMixin, ListView):
    template_name = 'transactions/transaction_report.html'
    model = Transaction
    balance = 0 # filter korar pore ba age amar total balance ke show korbe
    
    def get_queryset(self):
        queryset = super().get_queryset().filter(
            account=self.request.user.account
        )
        start_date_str = self.request.GET.get('start_date')
        end_date_str = self.request.GET.get('end_date')
        
        if start_date_str and end_date_str:
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
            
            queryset = queryset.filter(timestamp__date__gte=start_date, timestamp__date__lte=end_date)
            self.balance = Transaction.objects.filter(
                timestamp__date__gte=start_date, timestamp__date__lte=end_date
            ).aggregate(Sum('amount'))['amount__sum']
        else:
            self.balance = self.request.user.account.balance
       
        return queryset.distinct() # unique queryset hote hobe
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update({
            'account': self.request.user.account
        })

        return context
    
        
class PayLoanView(LoginRequiredMixin, View):
    def get(self, request, loan_id):
        loan = get_object_or_404(Transaction, id=loan_id)
        print(loan)
        if loan.loan_approve:
            user_account = loan.account
                # Reduce the loan amount from the user's balance
                # 5000, 500 + 5000 = 5500
                # balance = 3000, loan = 5000
            if loan.amount < user_account.balance:
                user_account.balance -= loan.amount
                loan.balance_after_transaction = user_account.balance
                user_account.save()
                loan.loan_approved = True
                loan.transaction_type = LOAN_PAID
                loan.save()
                return redirect('loan_list')
            else:
                messages.error(
            self.request,
            f'Loan amount is greater than available balance'
        )
        return redirect('loan_list')



class LoanListView(LoginRequiredMixin,ListView):
    model = Transaction
    template_name = 'transactions/loan_request.html'
    context_object_name = 'loans' # loan list ta ei loans context er moddhe thakbe
    
    def get_queryset(self):
        user_account = self.request.user.account
        queryset = Transaction.objects.filter(account=user_account,transaction_type=3)
        print(queryset)
        return queryset
    
    
    
class TransferView(LoginRequiredMixin, CreateView):
    template_name = 'transactions/money_transfer.html'
    form_class = TransferForm
    success_url = reverse_lazy('transfer_amount')
    title = 'Transfer Money'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update({
            'title': self.title
        })
        return context

    def form_valid(self, form):
        amount = form.cleaned_data.get('amount')
        transfer_account_no = form.cleaned_data.get('transfer_account')
        active_account = self.request.user.account

        transfer_account = UserBankAccount.objects.filter(account_no=transfer_account_no).first()
        if transfer_account is None:
            messages.error(self.request, 'Transfer account does not exist.')
            return self.form_invalid(form)

        if active_account.balance <= 0 or active_account.balance < amount:
            messages.error(self.request, 'Insufficient balance.')
            return self.form_invalid(form)

        # Deduct from sender and add to receiver
        transfer_account.balance += amount
        active_account.balance -= amount
        active_account.save()
        transfer_account.save()

        # Send email to sender
        send_transaction_email(
            user=self.request.user,
            amount=amount,
            subject="Money Transfer Successful",
            template="transactions/sender_email.html"
        )

        # Send email to receiver
        send_transaction_email(
            user=transfer_account.user,
            amount=amount,
            subject="Money Received",
            template="transactions/receiver_email.html"
        )

        messages.success(self.request, 'Transfer successful.')
        return super().form_valid(form)


