from django.shortcuts import render, redirect, get_object_or_404
from django.views.generic import ListView, View
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import JsonResponse, Http404
from django.urls import reverse
from django.contrib import messages
from property.models import Property
import json
from django.utils import timezone
from .forms import TaskForm
from .models import Task, TaskImage
from dateutil.relativedelta import relativedelta
import datetime
from django.db.models import Q
import uuid
from types import SimpleNamespace
from accounts.utils import get_visible_user_ids, get_effective_user


# Attachment limits (kept in sync with the client-side cap in create.html).
MAX_TASK_IMAGES = 10
MAX_TASK_IMAGE_SIZE = 5 * 1024 * 1024  # 5 MB per image

# How far ahead to generate occurrences when a repeating task has no end date.
# An unbounded series can't be pre-created, so each frequency gets a sensible
# horizon that keeps the number of generated rows reasonable.
NO_END_HORIZON = {
    'Daily': relativedelta(months=3),
    'Weekly': relativedelta(months=6),
    'Monthly': relativedelta(years=2),
    'Quarterly': relativedelta(years=3),
    'Yearly': relativedelta(years=5),
}
# Hard safety cap on generated occurrences, regardless of horizon/frequency.
MAX_TASK_OCCURRENCES = 366


def save_task_images(task, files, already_saved=0):
    """Save uploaded images to a task, enforcing the count and size caps."""
    remaining = max(0, MAX_TASK_IMAGES - already_saved)
    saved = 0
    for img_file in files:
        if saved >= remaining:
            break
        if img_file.size > MAX_TASK_IMAGE_SIZE:
            continue
        TaskImage.objects.create(task=task, image=img_file)
        saved += 1
    return saved


class TaskListView(LoginRequiredMixin, ListView):
    template_name = 'frontend/tasks/list.html'
    model = Task
    context_object_name = 'tasks'
    paginate_by = 10

    def get_template_names(self):
        # The header search box fetches this via AJAX (see list.html) so typing
        # updates the results without reloading the whole page.
        if self.request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return ['frontend/tasks/_task_list_partial.html']
        return [self.template_name]

    def get(self, request, *args, **kwargs):
        try:
            return super().get(request, *args, **kwargs)
        except Http404:
            if request.GET.get('page'):
                query_params = request.GET.copy()
                if not hasattr(self, 'object_list'):
                    self.object_list = self.get_queryset()
                paginator = self.get_paginator(self.object_list, self.paginate_by)
                query_params['page'] = paginator.num_pages
                url = request.path
                if query_params:
                    url += '?' + query_params.urlencode()
                return redirect(url)
            raise

    def get_queryset(self):
        base_queryset = super().get_queryset().filter(created_by__in=get_visible_user_ids(self.request.user)).select_related('property')
        status_filter = self.request.GET.get('status', 'pending')
   

        # Filter tasks based on the selected status
        if status_filter == 'pending':
            tasks = base_queryset.filter(completed=False)
        elif status_filter == 'done':
            tasks = base_queryset.filter(completed=True)
        else: # 'all' or any other value
            tasks = base_queryset

        # Apply search filter if a query is provided
        search_query = self.request.GET.get('search', '')
        if search_query:
            tasks = tasks.filter(
                Q(property__title__icontains=search_query) |
                Q(task_type__icontains=search_query) |
                Q(details__icontains=search_query) |
                Q(assigned_to__icontains=search_query)
            )

        # Due-date filter(only for pending tasks)
        due_filter = self.request.GET.get('due', '')
        if status_filter == 'pending' and due_filter in ('overdue', 'this_week', 'later'):
            today = datetime.date.today()
            week_end = today + datetime.timedelta(days=(6 - today.weekday()))
            if due_filter == 'overdue':
                tasks = tasks.filter(date__lt=today)
            elif due_filter == 'this_week':
                tasks = tasks.filter(date__gte=today, date__lte=week_end)
            elif due_filter == 'later':
                tasks = tasks.filter(date__gt=week_end)

        if status_filter == 'done':
            tasks = tasks.order_by('-date', '-time')
        else:
            tasks = tasks.order_by('date', 'time')
        return tasks



    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        tasks_on_page = context['object_list']
        status_filter = self.request.GET.get('status', 'pending')
        today = datetime.date.today()

        for task in tasks_on_page:
            if task.date:
                task.is_overdue = task.date < today
                if not task.is_overdue:
                    delta = task.date - today
                    task.days_until_due = delta.days
                else:
                    task.days_until_due = 0
            else:
                task.is_overdue = False
                task.days_until_due = 0

        base_queryset = self.model.objects.filter(created_by__in=get_visible_user_ids(self.request.user))
        context['status_filter'] = status_filter
        context['all_tasks_count'] = base_queryset.count()
        context['pending_tasks_count'] = base_queryset.filter(completed=False).count()
        context['done_tasks_count'] = base_queryset.filter(completed=True).count()
        context['search_query'] = self.request.GET.get('search', '')

        # Counts for the due-date filter chips (pending tasks only)
        week_end = today + datetime.timedelta(days=(6 - today.weekday()))
        pending_queryset = base_queryset.filter(completed=False, date__isnull=False)
        context['due_filter'] = self.request.GET.get('due', '')
        context['overdue_count'] = pending_queryset.filter(date__lt=today).count()
        context['this_week_count'] = pending_queryset.filter(date__gte=today, date__lte=week_end).count()
        context['later_count'] = pending_queryset.filter(date__gt=week_end).count()

        return context

class TaskCreateView(LoginRequiredMixin, View):
    template_name = 'frontend/tasks/create.html'
    form_class = TaskForm

    def dispatch(self, request, *args, **kwargs):
        # Tasks can only be created once the host's profile is complete. Blocks
        # direct-URL access too, not just the "Create Task" button (which shows
        # the complete-profile modal). Uses the effective user so co-hosts are
        # gated by the host's profile.
        if request.user.is_authenticated and not get_effective_user(request.user).is_profile_complete():
            messages.error(request, 'Please complete your profile before creating a task.')
            return redirect('profile')
        return super().dispatch(request, *args, **kwargs)

    def get(self, request, *args, **kwargs):
        form = self.form_class(user=request.user)
        properties = Property.objects.filter(created_by__in=get_visible_user_ids(request.user), status='Active')
        context = {
            'form': form,
            'properties': properties,
            'is_edit': False,
        }
        return render(request, self.template_name, context)

    def post(self, request, *args, **kwargs):
        form = self.form_class(request.POST, request.FILES, user=request.user)
        if form.is_valid():
            base_task = form.save(commit=False)
            effective_user = get_effective_user(request.user)
            base_task.created_by = effective_user

            repeat_option = base_task.repeat
            start_date = base_task.date
            end_date = base_task.repeat_till

            img_files = request.FILES.getlist('task_images')

            delta_map = {
                'Daily': relativedelta(days=1),
                'Weekly': relativedelta(weeks=1),
                'Monthly': relativedelta(months=1),
                'Quarterly': relativedelta(months=3),
                'Yearly': relativedelta(years=1),
            }
            delta = delta_map.get(repeat_option)

            if repeat_option and repeat_option != 'None' and start_date and delta:
                # "No end date" (repeat_till left empty) → generate a bounded
                # horizon instead of skipping recurrence entirely. The stored
                # repeat_till stays as the user set it (None = no end date).
                loop_end = end_date or (start_date + NO_END_HORIZON.get(repeat_option, relativedelta(years=1)))

                tasks_to_create = []
                current_date = start_date
                recurrence_id = str(uuid.uuid4())
                while current_date <= loop_end and len(tasks_to_create) < MAX_TASK_OCCURRENCES:
                    tasks_to_create.append(Task(
                        property=base_task.property,
                        title=base_task.title,
                        details=base_task.details,
                        date=current_date,
                        time=base_task.time,
                        repeat=base_task.repeat,
                        repeat_till=base_task.repeat_till,
                        task_type=base_task.task_type,
                        other_explanation=base_task.other_explanation,
                        assigned_to=base_task.assigned_to,
                        phone=base_task.phone,
                        country_code=base_task.country_code,
                        email=base_task.email,
                        created_by=effective_user,
                        recurrence_id=recurrence_id,
                    ))
                    current_date += delta
                Task.objects.bulk_create(tasks_to_create)
                if img_files:
                    # bulk_create may not set PKs on SQLite; query explicitly
                    first_task = Task.objects.filter(recurrence_id=recurrence_id).order_by('date').first()
                    if first_task:
                        save_task_images(first_task, img_files)
            else:
                base_task.save()
                save_task_images(base_task, img_files)

            messages.success(request, 'Task created successfully!')
            return redirect(reverse('tasks:task-list'))
        else:
            messages.error(request, 'Please correct the errors below.')
            properties = Property.objects.filter(created_by__in=get_visible_user_ids(request.user), status='Active')
            return render(request, self.template_name, {'form': form, 'properties': properties, 'is_edit': False})

class TaskEditView(LoginRequiredMixin, View):
    template_name = 'frontend/tasks/create.html'
    form_class = TaskForm

    def get(self, request, pk, *args, **kwargs):
        task = get_object_or_404(Task, pk=pk, created_by__in=get_visible_user_ids(request.user))
        form = self.form_class(instance=task, user=request.user)
        properties = Property.objects.filter(created_by__in=get_visible_user_ids(request.user), status='Active')
        context = {
            'form': form,
            'properties': properties,
            'is_edit': True,
            'task': task,
            'existing_images': task.images.all(),
        }
        return render(request, self.template_name, context)

    def post(self, request, pk, *args, **kwargs):
        task = get_object_or_404(Task, pk=pk, created_by__in=get_visible_user_ids(request.user))
        
        # Create a mutable copy of the POST data
        post_data = request.POST.copy()

        # If the task is a repeating one, some fields are disabled and won't be in POST data.
        # We must add them back from the original instance to prevent data loss.
        if task.repeat != 'None':
            disabled_fields_map = {
                'property': task.property.id,
                'repeat': task.repeat,
                'task_type': task.task_type,
            }

            # The date input is only disabled for occurrences that have already
            # passed; a task due today or later is rescheduled from the form.
            if not (task.date and task.date >= datetime.date.today()):
                disabled_fields_map['date'] = task.date.strftime('%Y-%m-%d') if task.date else ''

            for field_name, field_value in disabled_fields_map.items():
                if field_name not in post_data:
                    post_data[field_name] = field_value

            # 'repeat_till' is conditionally disabled by JS, so we handle it separately.
            # This is only relevant for repeating tasks.
            if 'repeat_till' not in post_data and task.repeat_till:
                post_data['repeat_till'] = task.repeat_till.strftime('%Y-%m-%d')

        form = self.form_class(post_data, request.FILES, instance=task, user=request.user)
        if form.is_valid():
            form.save()
            save_task_images(task, request.FILES.getlist('task_images'),
                             already_saved=task.images.count())
            messages.success(request, 'Task updated successfully!')
            return redirect(reverse('tasks:task-list'))
        else:
            messages.error(request, 'Please correct the errors below.')
            properties = Property.objects.filter(created_by__in=get_visible_user_ids(request.user), status='Active')
            return render(request, self.template_name, {
                'form': form, 'properties': properties,
                'is_edit': True, 'task': task,
                'existing_images': task.images.all(),
            })


class UpdateTaskStatusView(LoginRequiredMixin, View):
    def post(self, request, pk, *args, **kwargs):
        try:
            task = Task.objects.get(pk=pk, created_by__in=get_visible_user_ids(request.user))
            data = json.loads(request.body)
            is_completed = data.get('completed', False)
            
            task.completed = is_completed
            task.save()

            # Recalculate counts for the current user to return to the frontend
            base_queryset = Task.objects.filter(created_by__in=get_visible_user_ids(request.user))
            pending_tasks_count = base_queryset.filter(completed=False).count()
            done_tasks_count = base_queryset.filter(completed=True).count()

            # Recalculate the due-date filter chip counts (pending tasks only)
            today = datetime.date.today()
            week_end = today + datetime.timedelta(days=(6 - today.weekday()))
            pending_queryset = base_queryset.filter(completed=False, date__isnull=False)
            overdue_count = pending_queryset.filter(date__lt=today).count()
            this_week_count = pending_queryset.filter(date__gte=today, date__lte=week_end).count()
            later_count = pending_queryset.filter(date__gt=week_end).count()

            # messages.success(request, 'Task status updated successfully!')
            return JsonResponse({
                'success': True,
                'pending_tasks_count': pending_tasks_count,
                'done_tasks_count': done_tasks_count,
                'overdue_count': overdue_count,
                'this_week_count': this_week_count,
                'later_count': later_count,
            })
        except Task.DoesNotExist:
            return JsonResponse({'success': False, 'error': 'Task not found.'}, status=404)
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)}, status=400)


class TaskDetailView(LoginRequiredMixin, View):
    template_name = 'frontend/tasks/task-details-view.html'

    def get(self, request, pk, *args, **kwargs):
        task = get_object_or_404(Task, pk=pk, created_by__in=get_visible_user_ids(request.user))
        today = datetime.date.today()
        if task.date:
            task.is_overdue = task.date < today
            task.days_until_due = (task.date - today).days if not task.is_overdue else 0
        else:
            task.is_overdue = False
            task.days_until_due = 0
        return render(request, self.template_name, {'task': task})


class TaskImageDeleteView(LoginRequiredMixin, View):
    def post(self, request, *args, **kwargs):
        try:
            data = json.loads(request.body)
            image_id = data.get('image_id')
            image = TaskImage.objects.get(pk=image_id, task__created_by__in=get_visible_user_ids(request.user))
            image.delete()
            return JsonResponse({'success': True})
        except TaskImage.DoesNotExist:
            return JsonResponse({'success': False, 'error': 'Image not found.'}, status=404)
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)}, status=400)


class TaskDeleteView(LoginRequiredMixin, View):
    def post(self, request, pk, *args, **kwargs):
        try:
            task = Task.objects.get(pk=pk, created_by__in=get_visible_user_ids(request.user))

            data = json.loads(request.body)
            delete_mode = data.get('delete_mode', 'single')
            if delete_mode == 'all' and task.recurrence_id:
                count, _ = Task.objects.filter(recurrence_id=task.recurrence_id, created_by__in=get_visible_user_ids(request.user)).delete()
            else:
                task.delete()
                count = 1

            # Recalculate counts
            base_queryset = Task.objects.filter(created_by__in=get_visible_user_ids(request.user))
            all_tasks_count = base_queryset.count()
            pending_tasks_count = base_queryset.filter(completed=False).count()
            done_tasks_count = base_queryset.filter(completed=True).count()

            message_text = f"{count} task{'s' if count != 1 else ''} deleted successfully."
            messages.success(request, message_text)

            return JsonResponse({
                'success': True,
                'message': message_text,
                'all_tasks_count': all_tasks_count,
                'pending_tasks_count': pending_tasks_count,
                'done_tasks_count': done_tasks_count
            })
        except Task.DoesNotExist:
            return JsonResponse({'success': False, 'error': 'Task not found.'}, status=404)
