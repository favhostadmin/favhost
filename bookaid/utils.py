from booking.models import Payment


def calculateTotalPayment(booking_id):
    try:

        payments = Payment.objects.filter(booking_id=booking_id, is_paid=True)

        total_payment = 0
        for pay in payments:
            if pay.type == 'Refundable to guest':
                total_payment -=pay.amount
            else:
                total_payment += pay.amount
        return total_payment
    except Exception as e:
        print(e)
        return 0